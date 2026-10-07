#include "tasks/task_main.h"
#include "main.h"
#include "cmsis_os.h"

#include "tasks/task_shared.h"



void mainTask(void *argument)
{
  /* init code for USB_DEVICE */
  MX_USB_DEVICE_Init();
  /* USER CODE BEGIN 5 */
  printf("Start of mainTask\r\n");
  osThreadSuspend(sensorQueryHandle);
  gpio_t cs_flash = {
      .GPIOx = NOR_CS_GPIO_Port,
      .Pin = NOR_CS_Pin};

  gpio_t rst_flash = {
      .GPIOx = NOR_RST_GPIO_Port,
      .Pin = NOR_RST_Pin,
  };

  mt25q_t flash = {
      .flash_spi.hspi = &hspi2,
      .flash_spi.cs_pin = cs_flash,
      .flash_spi.spiSem = norSemaphoreHandle,
      .rst_pin = rst_flash,
  };



  mt25q_init(&flash);
  printf("\033c\033[0;32mProgram Start\033[0m\r\n");

  if (__HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST)) {
    printf("Reset by IWDG\r\n");
  }
  
  fs_init(&flash);
  lfs_file_t file;
  printf("LFS Init\r\n");
  osDelay(100);
  // mount the filesystem
  int err = lfs_mount(&lfs, &cfg);
  printf("LFS Mount %d\r\n",err);
  // reformat if we can't mount the filesystem
  // this should only happen on the first boot
  if (err)
  {
    printf("lfs mount error\r\n");
    lfs_format(&lfs, &cfg);
    lfs_mount(&lfs, &cfg);
  }


  // read current count
  uint32_t boot_count = 0;
  lfs_file_open(&lfs, &file, "boot_count", LFS_O_RDWR | LFS_O_CREAT);
  lfs_file_read(&lfs, &file, &boot_count, sizeof(boot_count));
  // update boot count
  boot_count += 1;
  lfs_file_rewind(&lfs, &file);
  lfs_file_write(&lfs, &file, &boot_count, sizeof(boot_count));
  osDelay(100);

  // remember the storage is not updated until the file is closed successfully
  lfs_file_close(&lfs, &file);

  // release any resources we were using
  lfs_unmount(&lfs);
  printf("After lfs_unmount\r\n");
  printf("boot_count: %ld\r\n", boot_count);
  // print the boot count


  osThreadResume(sensorQueryHandle);
  obc_sensor_data_t _obc_sensors;
  eps_sensor_data_t _eps_sensors;

  uint8_t sensors_data_ready = 0;

   rv3028c7_t rtc = {
      .rv3028c7_i2c_hal.hi2c = &hi2c4,
      .address = 0x52,
  };
  rv3028c7_init(&rtc);
  date_time_t datetime;
  uint8_t temp_commu_data_buff[COMMU_BUF_SIZE];  // accumulation buffer
  uint8_t decode_buf[COMMU_BUF_SIZE] = {0};
  uint8_t kiss_content[COMMU_BUF_SIZE] = {0};
  kiss_frame_t output_frame = {
    .content = kiss_content
  };

  uint8_t local_eps_state = EPS_DATA_NO_DATA;
  // osDelay(2000);
  osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
  /* Infinite loop */

  uint8_t eps_beacon_buf[EPS_PACKED_BUFFER_SIZE] = {0};
  uint8_t eps_beacon_len = 0;

  uint8_t beacon_content_buf[MAX_BEACON_PACKET_SIZE] = {0};
  uint16_t beacon_content_len = 0;
  uint32_t beacon_timeNow = 0;
  osEventFlagsClear(systemStateFlagHandle,SYSTEM_STATE_ALL);
  osEventFlagsSet(systemStateFlagHandle,SYSTEM_STATE_BEACON);

  uint32_t data_polling_timeNow = 0;
  uint32_t local_state;

  uint32_t last_commu_timeNow = 0;

  uint8_t downlink_seq_num = 0;

  commu_file_data downlink_file_data;
  uint32_t payload_flag_store = 0;


  for(;;)
  {
    local_state = osEventFlagsGet(systemStateFlagHandle);
    uint32_t ticks = osKernelGetTickCount();
    uint32_t freq  = osKernelGetTickFreq();

      // Convert ticks to milliseconds
    uint32_t millis = (ticks * 1000U) / freq;

    if (millis - data_polling_timeNow > DATA_POLLING_INTERVAL){
        uint32_t local_payload_state = osEventFlagsGet(payloadFlagHandle);
        // printf("local state %ld, payload state %ld\r\n",local_state,osEventFlagsGet(payloadFlagHandle));

        printf("System state : ");
        if (local_state & SYSTEM_STATE_BEACON){
          printf("Beacon\r\n");
        }
        if (local_state & SYSTEM_STATE_DOWNLINK){
          printf("Downlink\r\n");
        }
        if (local_state & SYSTEM_STATE_WAIT_ACK){
          printf("  - Downlink wait for GS ACK\r\n");
        }

        printf("Payload state : ");
        if (local_payload_state & PAYLOAD_FLAG_IDLE){
          printf("IDLE, ");
        }
        if (local_payload_state & PAYLOAD_FLAG_POLL_CAPTURE){
          printf("POLL_CAPTURE, ");
        }
        if (local_payload_state & PAYLOAD_FLAG_REQUEST_STATUS){
          printf("REQUEST_STATUS, ");
        }
        if (local_payload_state & PAYLOAD_FLAG_IMAGE_REQUEST){
          printf("IMAGE_REQUEST, ");
        }
        if (local_payload_state & PAYLOAD_FLAG_IMAGE_TRANSFER){
          printf("IMAGE_TRANSFER, ");
        }
        if (local_payload_state & PAYLOAD_FLAG_PING){
          printf("PING, ");
        }
        if (local_payload_state & PAYLOAD_FLAG_RESPONSE_PING){
          printf("RESPONSE_PING, ");
        }
        if (local_payload_state & PAYLOAD_FLAG_IMAGE_DATA){
          printf("IMAGE_DATA, ");
        }
        printf("\r\n");

        sensors_data_ready = 0;
        HAL_StatusTypeDef ret = rv3028c7_read_time(&rtc, &datetime);

        HAL_RTC_SetDate(&hrtc, &(RTC_DateTypeDef){.Year = datetime.year, .Month = datetime.month, .Date = datetime.day}, RTC_FORMAT_BIN);
        HAL_RTC_SetTime(&hrtc, &(RTC_TimeTypeDef){.Hours = datetime.hour, .Minutes = datetime.min, .Seconds = datetime.sec}, RTC_FORMAT_BIN);
        
        osStatus_t os_ret = osMutexAcquire(sensorsMutexHandle,300);
        if (os_ret != osOK){
            printf("Aquire OBC Sensor error\r\n");
        }
        else{
            _obc_sensors.temp = obc_sensors_data.temp;
            _obc_sensors.datetime = datetime;
            _eps_sensors = eps_sensors_data;
            sensors_data_ready = 1;
            local_eps_state = eps_state;
            eps_state = EPS_DATA_CONSUMED;
            osMutexRelease(sensorsMutexHandle);
        }
      // if (!sensors_data_ready){
      //   continue;
      // }
      // printf("Temperature : %ld\r\n", _obc_sensors.temp);
      // printf("20%02d/%02d/%02d %02d:%02d:%02d\r\n", _obc_sensors.datetime.year, _obc_sensors.datetime.month, _obc_sensors.datetime.day, _obc_sensors.datetime.hour, _obc_sensors.datetime.min, _obc_sensors.datetime.sec);

      if (local_eps_state == EPS_DATA_OK){
        for (int i = 0; i < EPS_NUM_VI_CHANNEL;i++){
          uint8_t channel = _eps_sensors.vi_sensor[i].channel;
          int16_t voltage = _eps_sensors.vi_sensor[i].voltage;
          int16_t current = _eps_sensors.vi_sensor[i].current;
          eps_data_state data_state = _eps_sensors.vi_sensor[i].data_state;
          if (data_state == EPS_DATA_OK){
            // printf("VI Sensor CH %d, Volage : %dmV, Current %dmA\r\n",channel,voltage,current);
          }
          _eps_sensors.vi_sensor[i].data_state = EPS_DATA_CONSUMED;
        }
    
        for (int i = 0; i < EPS_NUM_OUTPUT_CHANNEL;i++){
          uint8_t channel = _eps_sensors.output_sensor[i].channel;
          int16_t voltage = _eps_sensors.output_sensor[i].voltage;
          int16_t current = _eps_sensors.output_sensor[i].current;
          eps_data_state data_state = _eps_sensors.output_sensor[i].data_state;
          if (data_state == EPS_DATA_OK){
            // printf("Output Sensor CH %d, Volage : %dmV, Current %dmA\r\n",channel,voltage,current);
          }
          _eps_sensors.output_sensor[i].data_state = EPS_DATA_CONSUMED;
        }
    
        for (int i = 0; i < EPS_NUM_OUTPUT_CHANNEL;i++){
          uint8_t channel = _eps_sensors.output_state[i].channel;
          uint8_t status = _eps_sensors.output_state[i].status;
          eps_data_state data_state = _eps_sensors.output_state[i].data_state;
          if (data_state != EPS_DATA_OK){
            continue;
          }
          // printf("Output State CH %d, State %d\r\n",channel,status);
          _eps_sensors.output_state[i].data_state = EPS_DATA_CONSUMED;
        }
    
        for (int i = 0; i < EPS_NUM_TEMP_BATT;i++){
          uint8_t channel = _eps_sensors.battery_temperature[i].channel;
          int16_t temp = _eps_sensors.battery_temperature[i].temperature * 1000;
          eps_data_state data_state = _eps_sensors.battery_temperature[i].data_state;
          if (data_state != EPS_DATA_OK){
            continue;
          }
          // printf("Battery Temperature CH %d, Temperature %d State %d\r\n",channel,temp,data_state);
          _eps_sensors.battery_temperature[i].data_state = EPS_DATA_CONSUMED;
        }
        local_eps_state = EPS_DATA_CONSUMED;

        eps_beacon_len = eps_pack_sensor_data(eps_beacon_buf,sizeof(_eps_sensors),&_eps_sensors);

      }


      data_polling_timeNow = millis;
      // printf("\r\n");
    }

    if (local_state & SYSTEM_STATE_DOWNLINK){
      HAL_IWDG_Refresh(&hiwdg); // Kick watchdog before slow SD+UART operations
      uint8_t buf_a[2048] = {0};
      uint8_t buf_b[2048] = {0};
      uint16_t buf_len = 0;
      uint8_t status = 0;
      uint16_t actual_read_len = 0;
      FATFS FatFS;
      FRESULT ret;
      FIL file;
      ret = f_mount(&FatFS,"",1);
      if (ret != FR_OK){
        status = 1;
      }
      ret = f_open(&file,downlink_file_data.file_name,FA_READ);
      if (ret != FR_OK){
        status = 1;
      }
      ret = f_lseek(&file,downlink_file_data.file_offset);
      if (ret != FR_OK){
        status = 1;
      }
      if (downlink_file_data.chunk_len > 1008) {
        downlink_file_data.chunk_len = 1008;
      }
      ret = f_read(&file,buf_a,downlink_file_data.chunk_len,(UINT*)&actual_read_len);
      if (ret != FR_OK){
        status = 1;
      }
      f_close(&file);
      ret = f_mount(NULL,"",0);
      buf_len = commu_file_downlink_encode(downlink_file_data,status,buf_a,actual_read_len,buf_b);
      if (buf_len == 0){
        printf("file downlink encode error\r\n");
      }
      buf_len = commu_encode(downlink_seq_num,COMMU_PAYLOAD_ID_OBC,PID_OBC_GS_RESPONSE_FILE_DATA,buf_len,buf_b,buf_a,65535);
      if (buf_len == 0){
        printf("downlink commu encode error\r\n");
      }
      buf_len = KISS_Encode_Custom_Cmd(buf_a, KISS_CMD_DATA_FRAME, buf_len, buf_b, sizeof(buf_b));
      if (buf_len == 0){
        printf("downlink kiss encode error\r\n");
      }
      HAL_UART_Transmit(&COM_UART,buf_b,buf_len,400); // Must be < IWDG timeout (~484ms)
      
      downlink_file_data.file_offset += actual_read_len;
      // printf("downlink %d file_name : %s chunk_len : %d, file_offset %ld\r\n",local_state,downlink_file_data.file_name,downlink_file_data.chunk_len,downlink_file_data.file_offset);
      
      downlink_seq_num++;
      last_commu_timeNow = millis;
      if (actual_read_len < downlink_file_data.chunk_len){
        printf("End of file reached. Downlink complete.\r\n");
        osEventFlagsClear(systemStateFlagHandle,SYSTEM_STATE_DOWNLINK);
        osEventFlagsSet(systemStateFlagHandle,SYSTEM_STATE_BEACON);
      }
      else if (downlink_seq_num % DOWNLINK_WINDOW_SIZE == 0){
        osEventFlagsClear(systemStateFlagHandle,SYSTEM_STATE_ALL);
        osEventFlagsSet(systemStateFlagHandle,SYSTEM_STATE_BEACON);
        beacon_timeNow = millis;
      }
      printf("after update sequence %d flag %ld\r\n",downlink_seq_num,osEventFlagsGet(systemStateFlagHandle));
    }

    if (millis - last_commu_timeNow > NO_COMMU_TIMEOUT){
      printf("Reset system state\r\n");
      osEventFlagsClear(systemStateFlagHandle,SYSTEM_STATE_ALL);
      osEventFlagsSet(systemStateFlagHandle,SYSTEM_STATE_BEACON);
      downlink_seq_num = 0;
      last_commu_timeNow = millis;
    }

    if ((millis - beacon_timeNow > BEACON_INTERVAL) && (local_state & SYSTEM_STATE_BEACON)){
      uint8_t date_time_buf[32] = {0};
      rv3028c7_pack_datetime(&_obc_sensors.datetime,date_time_buf);
      uint8_t date_time_buf_len = 7;

      uint8_t temperature_buf[4];
      uint8_t temperature_buf_len = tmp1075_pack_temperature(_obc_sensors.temp,temperature_buf);

      uint8_t beacon_packet[MAX_BEACON_PACKET_SIZE] = {0};
      uint16_t current_idx = 0U;
      
      (void)memcpy(&beacon_packet[current_idx], (const void *)eps_beacon_buf, (size_t)eps_beacon_len);
      current_idx += (uint16_t)eps_beacon_len;

      (void)memcpy(&beacon_packet[current_idx], (const void *)date_time_buf, (size_t)date_time_buf_len);
      current_idx += (uint16_t)date_time_buf_len;

      (void)memcpy(&beacon_packet[current_idx], (const void *)temperature_buf, (size_t)temperature_buf_len);
      current_idx += (uint16_t)temperature_buf_len;

      (void)memcpy(beacon_content_buf,(const void *)beacon_packet,(size_t)current_idx);
      beacon_content_len = current_idx;
      if (beacon_content_len > 0){
        uint8_t osi_buf[200];
        uint8_t seq_num = 0;
        uint8_t payload_id = 0;
        uint8_t osi_buf_len = commu_encode(seq_num,payload_id,PID_OBC_GS_BEACON,beacon_content_len,beacon_content_buf,osi_buf,200);
        
        uint8_t beacon_kiss[200];
        uint8_t beacon_kiss_len = KISS_Encode_Custom_Cmd(osi_buf, KISS_CMD_DATA_FRAME, osi_buf_len, beacon_kiss, sizeof(beacon_kiss));
        printf("Broadcast beacon");
        if (beacon_content_len < 121){
          printf(",No EPS Response still...");
        }
        printf("\r\n");
        
        HAL_UART_Transmit_IT(&COM_UART,beacon_kiss,beacon_kiss_len);
        beacon_content_len = 0;
      }
      beacon_timeNow = millis;
    }

    if (osMutexAcquire(uartMutexHandle,UART_MUTEX_TIMEOUT) == osOK){
      if (commu_data_ready){
        commu_data_ready = 0;
        printf("commu ready\r\n");
        memcpy(temp_commu_data_buff,commu_global_buff,commu_size);
        uint16_t buff_size = commu_size;
        uint8_t dekissed_buff[256];
        kiss_status_t dekissed_len = KISS_Decode(temp_commu_data_buff,buff_size,dekissed_buff);
        commu_header_t commu_request_header;
        uint8_t commu_payload[128] = {0};
        
        // Check for 0xAC (GS ACK) before COMMU decode
        // if (temp_commu_data_buff[1] == 0xAC) {
        //     printf("[OBC] Received ACK from GS\r\n");
        //     osEventFlagsClear(systemStateFlagHandle, SYSTEM_STATE_WAIT_ACK | SYSTEM_STATE_BEACON);
        //     osEventFlagsSet(systemStateFlagHandle, SYSTEM_STATE_DOWNLINK);
        //     osMutexRelease(uartMutexHandle);
        //     continue; // Skip COMMU decode for ACK
        // }
        
        commu_status_t status_commu =  commu_decode(dekissed_buff,dekissed_len,&commu_request_header,commu_payload, sizeof(commu_payload));
        // kiss_status_t status_kiss = KISS_UnwrapFrame(temp_commu_data_buff,buff_size,decode_buf,&output_frame);
        

        // printf("ret = %d dekissed len %d\r\n",status_commu,dekissed_len);
        if (status_commu == COMMU_VALID_DATA){
          // printf("Valid commu data\r\n");
          if (commu_request_header.payload_id == COMMU_PAYLOAD_ID_VR){
            uint8_t commu_vr_request_payload[64];
            int16_t commu_vr_request_len = 0;
            uint8_t commu_content[128];
            int16_t commu_len = 0;
            uint32_t osRet = osErrorValue; /* Initialize with error value */
            switch (commu_request_header.pid)
            {
            case PID_GS_VR_REQUEST_COPY_IMAGE_TO_SD:
              printf("Download image command\r\n");
              printf("ACK to COMMU\r\n");
              osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_IMAGE_REQUEST);
              osEventFlagsClear(payloadFlagHandle, PAYLOAD_FLAG_IDLE);
              uint8_t file_req_data[] = {0x01, 0xFF, 0xFF}; /* File ID (1), Chunk ID (2)*/
              commu_vr_request_len = payload_encode(COMMU_PAYLOAD_ID_VR,PID_GS_VR_REQUEST_COPY_IMAGE_TO_SD,3,file_req_data,commu_vr_request_payload,64);
              commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_REQUEST_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
              CDC_Transmit_FS(commu_content, commu_len);
              // osRet = osEventFlagsWait(payloadFlagHandle,PAYLOAD_FLAG_IDLE,osFlagsWaitAll | osFlagsNoClear,30000); /* Wait for VR to respond to image request (or at least ping) */ 
              osRet = osEventFlagsWait(payloadFlagHandle,PAYLOAD_FLAG_IMAGE_TRANSFER,osFlagsWaitAll | osFlagsNoClear,1000); /* Wait for VR to respond to image request (or at least ping) */ 
              uint8_t status = 0; /* Assume success for ACK */ 
              printf("Wait for image transfer response, osRet = %ld\r\n", osRet);
              if (osRet == osFlagsErrorTimeout)
              {
                status = 1; /* Set error status */
              }
              printf("ACK to GS with status %d\r\n", status);
              commu_vr_request_len = commu_encode(0,COMMU_PAYLOAD_ID_VR,PID_VR_GS_RESPONSE_COPY_IMAGE_TO_SD,1,&status,commu_vr_request_payload,64);
              commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_DATA_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
              HAL_UART_Transmit_IT(&COM_UART,commu_content,commu_len);
              break;
            case PID_GS_VR_REQUEST_CAPTURE:
              printf("GS Requests to Capture\r\n");
              osEventFlagsClear(payloadFlagHandle, PAYLOAD_FLAG_IDLE);
              osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_POLL_CAPTURE);
              commu_vr_request_len = payload_encode(COMMU_PAYLOAD_ID_VR,PID_GS_VR_REQUEST_CAPTURE,0,NULL,commu_vr_request_payload,64);
              commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_REQUEST_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
              CDC_Transmit_FS(commu_content, commu_len);
              uint8_t tmp[2] = {0,0};
              commu_vr_request_len = commu_encode(0,COMMU_PAYLOAD_ID_VR,PID_VR_GS_RESPONSE_CAPTURE,2,tmp,commu_vr_request_payload,128);
              commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_DATA_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
              HAL_UART_Transmit_IT(&COM_UART,commu_content,commu_len);
              break;
            case PID_GS_VR_REQUEST_PI_STATUS:
              printf("GS Requests PI Status\r\n");
              commu_vr_request_len = payload_encode(COMMU_PAYLOAD_ID_VR,PID_GS_VR_REQUEST_PING,0,NULL,commu_vr_request_payload,64);
              osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
              osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_REQUEST_STATUS);
              commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_REQUEST_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
              CDC_Transmit_FS(commu_content, commu_len);
              break;
            case PID_GS_VR_REQUEST_PING:
              printf("GS Requests PI Ping\r\n");
              if (osEventFlagsGet(payloadFlagHandle) & PAYLOAD_FLAG_IDLE){
                commu_vr_request_len = payload_encode(COMMU_PAYLOAD_ID_VR,PID_GS_VR_REQUEST_PING,0,NULL,commu_vr_request_payload,64);
                osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
                osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_PING);
                commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_REQUEST_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
                CDC_Transmit_FS(commu_content, commu_len);
                uint32_t getFlagRet = osEventFlagsWait(payloadFlagHandle,PAYLOAD_FLAG_RESPONSE_PING,osFlagsWaitAll,1000);
                if (getFlagRet == osErrorTimeout){
                  printf("\033[0;31mVR Ping Timeout sent %d bytes\033[0m\r\n",commu_len);
                  osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_PING);
                  // osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
                  commu_vr_request_len = commu_encode(0,COMMU_PAYLOAD_ID_VR,PID_GS_VR_NAK,0,NULL,commu_vr_request_payload,64);
                }
                else{
                  printf("\033[0;32mPayload Response Ping\033[0m\r\n");
                  commu_vr_request_len = commu_encode(0,COMMU_PAYLOAD_ID_VR,PID_VR_GS_RESPONSE_PING,0,NULL,commu_vr_request_payload,64);
                }
              }
              else{
                commu_vr_request_len = commu_encode(0,COMMU_PAYLOAD_ID_VR,PID_GS_VR_NAK,0,NULL,commu_vr_request_payload,64);
              }
              commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_DATA_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
              osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
              HAL_UART_Transmit_IT(&COM_UART, commu_content, commu_len);
              break;
            case PID_GS_VR_REQUEST_SHUTDOWN:
              printf("GS Requests VR Shutdown (DANGEROUS)\r\n");
              
              /* 1. Fire shutdown KISS frame to Pi immediately via CDC */
              uint8_t pi_cmd[32] = {0};
              uint16_t pi_len = KISS_WrapFrame(KISS_PAYLOAD_ID_VR, KISS_VR_PID_SHUTDOWN, NULL, 0, KISS_CMD_DATA, pi_cmd, sizeof(pi_cmd));
              CDC_Transmit_FS(pi_cmd, pi_len);
              printf("Shutdown command fired to VR Pi (Fire & Forget)\r\n");

              /* 2. Proxy the ACK back to GS immediately so it doesn't wait */
              uint8_t gs_ack_payload[32] = {0};
              // Note: We use COMMU_PAYLOAD_ID_VR (0x01) so GS knows it refers to the Pi
              uint16_t gs_ack_len = commu_encode(commu_request_header.seq_num, COMMU_PAYLOAD_ID_VR, PID_GS_VR_REQUEST_SHUTDOWN, 0, NULL, gs_ack_payload, 32);
              uint8_t gs_ack_kiss[64] = {0};
              uint16_t gs_ack_kiss_len = KISS_Encode_Custom_Cmd(gs_ack_payload, KISS_CMD_DATA_FRAME, gs_ack_len, gs_ack_kiss, sizeof(gs_ack_kiss));
              HAL_UART_Transmit_IT(&COM_UART, gs_ack_kiss, gs_ack_kiss_len);
              break;
            default:
              printf("GS PID that does not exists in the system\r\n");
              break;
            }
          }
          else if (commu_request_header.payload_id == COMMU_PAYLOAD_ID_OBC){
            uint8_t commu_vr_request_payload[64];
            int16_t commu_vr_request_len = 0;
            uint8_t commu_content[128];
            int16_t commu_len = 0;
            uint8_t kiss_content[128];
            int16_t kiss_len = 0;
            uint32_t osRet = osErrorValue;
            switch (commu_request_header.pid){
              case PID_GS_OBC_REQUEST_PING:
                printf("GS Ping OBC\r\n");
                uint8_t response_ping_buf[32] = {0};
                uint8_t response_ping_len = commu_encode(0,COMMU_PAYLOAD_ID_OBC,PID_OBC_GS_RESPONSE_PING,0,NULL,response_ping_buf,10);

                uint8_t kiss_encoded_res[32] = {0};
                uint8_t kiss_respond_len = KISS_Encode_Custom_Cmd(response_ping_buf, KISS_CMD_DATA_FRAME, response_ping_len, kiss_encoded_res, sizeof(kiss_encoded_res));

                HAL_StatusTypeDef ret = HAL_UART_Transmit_IT(&COM_UART,kiss_encoded_res,kiss_respond_len);
                printf("Responsded ping from commu with return %d from UART\r\n",ret);
                break;
              case PID_GS_OBC_REQUEST_LIST_FILE:
                printf("GS Request List File\r\n");
                uint32_t currentPayloadFlag = osEventFlagsGet(payloadFlagHandle);
                if (currentPayloadFlag & (PAYLOAD_FLAG_IMAGE_REQUEST | PAYLOAD_FLAG_IMAGE_TRANSFER)){
                  printf("\033[0;31mNot now, payload file copying\033[0m\r\n");
                  break;
                }
                FATFS FatFs;
                FRESULT res;
                DIR dir;
                FILINFO fno;
                printf("\r\n");

                res = f_mount(&FatFs,"",1);
                if (res != FR_OK){
                  printf("Mount error\r\n");
                  break;
                }
                char files_name[20][256];
                uint8_t file_count = 0;
                // Open the root directory
                res = f_opendir(&dir, "/");
                if (res == FR_OK) {
                    for (;;) {
                        // Read a directory item
                        res = f_readdir(&dir, &fno);
                        if (res != FR_OK || fno.fname[0] == 0) break; // End of directory

                        // Check if it is a directory or file
                        if (fno.fattrib & AM_DIR) {
                            printf("Dir: %s\r\n", fno.fname);
                        } else {
                            printf("File: %s (Size: %lu)\r\n", fno.fname, (unsigned long)fno.fsize);
                            strcpy(files_name[file_count],fno.fname);
                            file_count++;
                        }
                    }
                    f_closedir(&dir);
                }
                res = f_mount(NULL,"",0);
                printf("\r\n");
                uint8_t list_file_buf[256] = {0};
                uint16_t list_file_encoded_len = commu_list_file_encode(files_name,file_count,list_file_buf,sizeof(list_file_buf));

                if (list_file_encoded_len == 0){
                  printf("Encode list file error\r\n");
                  break;
                }

                uint8_t commu_list_file_encoded[256] = {0};
                uint16_t commu_list_file_encoded_len = commu_encode(0,COMMU_PAYLOAD_ID_OBC,PID_OBC_GS_RESPONSE_LIST_FILE,list_file_encoded_len,list_file_buf,commu_list_file_encoded,512); 

                uint8_t kiss_list_file_encoded[256] = {0};
                uint16_t kiss_list_file_encoded_len = KISS_Encode_Custom_Cmd(commu_list_file_encoded, KISS_CMD_DATA_FRAME, commu_list_file_encoded_len, kiss_list_file_encoded, sizeof(kiss_list_file_encoded));

                ret = HAL_UART_Transmit_IT(&COM_UART,kiss_list_file_encoded,kiss_list_file_encoded_len);
                printf("Responsded ping from commu with return %d from UART\r\n",ret);

                break;
              case PID_GS_OBC_REQUEST_FILE_INFO:
                printf("GS Request File info\r\n");
                uint32_t currentPayloadFlagForInfo = osEventFlagsGet(payloadFlagHandle);
                if (currentPayloadFlagForInfo & (PAYLOAD_FLAG_IMAGE_REQUEST | PAYLOAD_FLAG_IMAGE_TRANSFER)){
                  printf("\033[0;31mNot now, payload file copying\033[0m\r\n");
                  break;
                }
                commu_file_data requested_file_for_info;
                commu_status_t decode_status_for_info = decode_file_info_request(commu_payload,commu_request_header.data_len,&requested_file_for_info);
                if (decode_status_for_info != COMMU_VALID_DATA){
                  printf("Decoded return %d\r\n",decode_status_for_info);
                  break;
                }
                printf("\r\n");
                FATFS FatFs_info;
                FRESULT res_info;
                FIL file_info;
                FILINFO fno_info;
                FSIZE_t file_size_info;
                res_info = f_mount(&FatFs_info,"",1);
                if (res_info != FR_OK){
                  printf("Mount error\r\n");
                  break;
                }
                res_info = f_open(&file_info, requested_file_for_info.file_name, FA_READ);
                if (res_info == FR_OK) {
                    file_size_info = f_size(&file_info);
                    f_close(&file_info);
                }
                else{
                  printf("open to get info error %d\r\n",res_info);
                }
                res_info = f_stat(requested_file_for_info.file_name, &fno);
                uint32_t epoch_info = 0;
                if (res_info == FR_OK) {
                    // 2. Map FatFs bitfields to a standard tm struct
                    struct tm t;
                    
                    // FatFs Date: bit15:9=Year(0-127), bit8:5=Month(1-12), bit4:0=Day(1-31)
                    // FatFs Year 0 starts at 1980
                    t.tm_year = ((fno.fdate >> 9) & 0x7F) + 80; 
                    t.tm_mon  = ((fno.fdate >> 5) & 0x0F) - 1; 
                    t.tm_mday = (fno.fdate & 0x1F);

                    // FatFs Time: bit15:11=Hour(0-23), bit10:5=Minute(0-59), bit4:0=Second/2(0-29)
                    t.tm_hour = (fno.ftime >> 11) & 0x1F;
                    t.tm_min  = (fno.ftime >> 5) & 0x3F;
                    t.tm_sec  = (fno.ftime & 0x1F) * 2;
                    
                    t.tm_isdst = -1; // Not considering Daylight Savings

                    // 3. Convert to Unix Epoch
                    time_t epoch = mktime(&t);
                    epoch_info = (uint32_t)epoch;
                }
                f_mount(NULL,"",0);
                printf("request %s size, which is = %ld, epoch = %ld\r\n",requested_file_for_info.file_name,file_size_info,epoch_info);
                uint8_t buf_a_info[64];
                uint8_t buf_b_info[64];
                uint8_t buf_len_info = 0;

                buf_len_info = commu_file_info_encode(0,file_size_info,epoch_info,buf_a_info);
                buf_len_info = commu_encode(0,COMMU_PAYLOAD_ID_OBC,PID_OBC_GS_RESPONSE_FILE_INFO,buf_len_info,buf_a_info,buf_b_info,64);
                if (buf_len_info == 0){
                  printf("commu encode error file info\r\n");
                }
                buf_len_info = KISS_Encode_Custom_Cmd(buf_b_info, KISS_CMD_DATA_FRAME, buf_len_info, buf_a_info, sizeof(buf_a_info));
                if (buf_len_info == 0){
                  printf("kiss encode error file info\r\n");
                }
                ret = HAL_UART_Transmit(&COM_UART,buf_a_info,buf_len_info,1000);
                printf("Responsded ping from commu with return %d from UART\r\n",ret);
                break;
              case PID_GS_OBC_REQUEST_FILE_DATA:
                printf("GS Request File data\r\n");
                uint32_t currentPayloadFlag1 = osEventFlagsGet(payloadFlagHandle);
                if (currentPayloadFlag1 & (PAYLOAD_FLAG_IMAGE_REQUEST | PAYLOAD_FLAG_IMAGE_TRANSFER)){
                  printf("\033[0;31mNot now, payload file copying\033[0m\r\n");
                  break;
                }
                commu_file_data requested_file;
                commu_status_t decode_status = decode_file_data_request(commu_payload,commu_request_header.data_len,&requested_file);
                if (decode_status != COMMU_VALID_DATA){
                  printf("Decoded return %d\r\n",decode_status);
                  break;
                }
                downlink_file_data = requested_file;
                printf("file_name : %s chunk_len : %d, file_offset %ld\r\n",requested_file.file_name,requested_file.chunk_len,requested_file.file_offset);
                osEventFlagsClear(systemStateFlagHandle,SYSTEM_STATE_BEACON | SYSTEM_STATE_WAIT_ACK);
                osEventFlagsSet(systemStateFlagHandle,SYSTEM_STATE_DOWNLINK);
                last_commu_timeNow = millis;
                break;
              case PID_GS_OBC_REQUEST_SYSTEM_STATUS:
                uint8_t status_response_data[32] = {0};
                printf("GS Requests System status\r\n");
                osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
                commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_DATA_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
                commu_vr_request_len = payload_encode(COMMU_PAYLOAD_ID_VR,PID_GS_VR_REQUEST_PI_STATUS,0,NULL,commu_vr_request_payload,64);
                commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_REQUEST_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
                CDC_Transmit_FS(commu_content, commu_len);
                osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_REQUEST_STATUS);
                uint32_t wait_status = osEventFlagsWait(payloadFlagHandle,PAYLOAD_FLAG_RESPONSE_STATUS,osFlagsWaitAll,1000);
                if (wait_status == osErrorTimeout){
                  printf("\033[0;31mVR Status Requests Timeout sent %d bytes\033[0m\r\n",commu_len);
                  osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_REQUEST_STATUS);
                  // osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
                  commu_vr_request_len = commu_encode(0,COMMU_PAYLOAD_ID_VR,PID_GS_VR_NAK,0,NULL,commu_vr_request_payload,64);
                }
                else{
                  printf("\033[0;32mPayload Response Status Requests\033[0m\r\n");
                  osRet = osMessageQueueGet(payloadStatueQueueHandle,(void*)status_response_data,NULL,1000);
                  printf("OS Ret from status message queue %ld\r\n",osRet);
                  if (osRet == osErrorTimeout){
                    printf("\033[0;31mVR Status Message Poll Timeout\033[0m\r\n");
                    osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_REQUEST_STATUS);
                    commu_vr_request_len = commu_encode(0,COMMU_PAYLOAD_ID_VR,PID_GS_VR_NAK,0,NULL,commu_vr_request_payload,64);
                  }
                  else if (osRet == osOK){
                    uint32_t payload_boot_count = 0;
                    uint32_t reserved_zero = 0; 
                    uint32_t uptime = 0;
                    uint8_t  cpu_percent = 0;
                    uint32_t temp_raw = 0;
                    uint8_t  ram_percent = 0;
                    uint8_t  disk_percent = 0;
                    uint8_t  cam_status = 0;
                    if (osRet == osOK){
                      // 2. Unpack based on the exact byte offsets from ">IIIBIBBB"
                      payload_boot_count    = unpack_be32(status_response_data + 0);  // I (4 bytes)
                      reserved_zero = unpack_be32(status_response_data + 4);  // I (4 bytes)
                      uptime        = unpack_be32(status_response_data + 8);  // I (4 bytes)
                      
                      cpu_percent   = status_response_data[12];               // B (1 byte)
                      
                      temp_raw      = unpack_be32(status_response_data + 13); // I (4 bytes)
                      
                      ram_percent   = status_response_data[17];               // B (1 byte)
                      disk_percent  = status_response_data[18];               // B (1 byte)
                      cam_status    = status_response_data[19];               // B (1 byte)
      
                      // 3. Print out the unpacked variables
                      printf("--- Unpacked Status Data ---\r\n");
                      printf("Boot Count   : %u\r\n", payload_boot_count);
                      printf("Timestamp    : %u\r\n", reserved_zero);
                      printf("Uptime       : %u seconds\r\n", uptime);
                      printf("CPU Percent  : %u%%\r\n", cpu_percent);
                      printf("Temp Raw     : %u\r\n", temp_raw);
                      printf("RAM Percent  : %u%%\r\n", ram_percent);
                      printf("Disk Percent : %u%%\r\n", disk_percent);
                      printf("Camera Status: %u\r\n", cam_status);
                    }

                    int err = lfs_mount(&lfs, &cfg);
                    if (err)
                    {
                      printf("lfs mount error\r\n");
                      lfs_format(&lfs, &cfg);
                      lfs_mount(&lfs, &cfg);
                    }
                    uint32_t boot_count = 0;
                    lfs_file_open(&lfs, &file, "boot_count", LFS_O_RDONLY);
                    lfs_file_read(&lfs, &file, &boot_count, sizeof(boot_count));
                    lfs_file_close(&lfs, &file);
                    lfs_unmount(&lfs);
                    printf("obc boot_count: %ld\r\n", boot_count);

                    uint8_t usb_status = 0;
                    if (osEventFlagsGet(payloadFlagHandle) & (~PAYLOAD_FLAG_IDLE)){
                      usb_status = 1;
                    }
                    printf("USB Status %ld\r\n",osEventFlagsGet(payloadFlagHandle));
                    uint8_t eps_status = 0;
                    commu_vr_request_len = commu_system_status_raw_downlink_encode(boot_count,usb_status,eps_status,status_response_data,20,commu_vr_request_payload);
                    commu_len = commu_encode(0,COMMU_PAYLOAD_ID_OBC,PID_GS_OBC_REQUEST_SYSTEM_STATUS,commu_vr_request_len,commu_vr_request_payload,status_response_data,256);
                    commu_len = KISS_Encode_Custom_Cmd(status_response_data, KISS_CMD_DATA_FRAME, commu_len, commu_content, sizeof(commu_content));
                  }
                }
                if (!(osEventFlagsGet(payloadFlagHandle) & (~PAYLOAD_FLAG_IDLE))){
                  osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
                }
                HAL_UART_Transmit_IT(&COM_UART, commu_content, commu_len);
                break;
              default:
                printf("Unknown OBC PID\r\n");
                break;
            }
          }
        }
      }
      osMutexRelease(uartMutexHandle);
    }
    uint32_t currentImgFlag = osEventFlagsGet(payloadFlagHandle);
    if (currentImgFlag != payload_flag_store){
      if (payload_flag_store & PAYLOAD_FLAG_IMAGE_TRANSFER && currentImgFlag & PAYLOAD_FLAG_IDLE){
        uint8_t status = 0; /* Assume success for ACK */ 
        uint16_t commu_vr_request_len = 0;
        uint8_t commu_vr_request_payload[64];
        uint8_t commu_content[128];
        uint16_t commu_len = 0;
        printf("ACK to GS with status %d\r\n", status);
        commu_vr_request_len = commu_encode(0,COMMU_PAYLOAD_ID_VR,PID_VR_GS_RESPONSE_COPY_IMAGE_TO_SD,1,&status,commu_vr_request_payload,64);
        commu_len = KISS_Encode_Custom_Cmd(commu_vr_request_payload, KISS_CMD_DATA_FRAME, commu_vr_request_len, commu_content, sizeof(commu_content));
        HAL_UART_Transmit_IT(&COM_UART,commu_content,commu_len);
      }
      payload_flag_store = currentImgFlag;
    }
  }
  /* USER CODE END 5 */
}

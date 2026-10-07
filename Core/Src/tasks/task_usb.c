#include "tasks/task_usb.h"
#include "main.h"
#include "cmsis_os.h"

#include "tasks/task_shared.h"



void usbTask(void *argument)
{
  /* USER CODE BEGIN usbTask */
  /* Infinite loop */
    usb_data_t usb_data_rx = { .is_new_message = 0, .len = 0 };
    uint32_t current_offset = 0;
    // uint16_t payload_len = 0;
    uint16_t current_chunk = 0;

    kiss_frame_t decoded_payload = { .content = payload_content };

    // osEventFlagsSet(payloadFlagHandle, PAYLOAD_FLAG_IDLE);

    //some variables for FatFs
    FATFS FatFs; 	//Fatfs handle
    FIL fil; 		//File handle
    FRESULT fres; //Result after operations

    payload_state payload_commu_state = PAYLOAD_STATE_IDLE;

    for (;;)
    {

        osStatus_t status = osMessageQueueGet(cdcDataQueueHandle,
                                             (void *)&usb_data_rx,
                                             NULL, PAYLOAD_RX_TIMEOUT);

          // printf("Queue Trigger %d %d\r\n",status,payload_commu_state);

        if (status == osErrorTimeout){
          if ((payload_commu_state == PAYLOAD_STATE_RX)){
            printf("USB RX Timeout, Reset State...\r\n");
            osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_IMAGE_REQUEST | PAYLOAD_FLAG_IMAGE_TRANSFER);
            osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_IDLE);
            payload_commu_state = PAYLOAD_STATE_IDLE;
            current_offset = 0;
          }
          continue;
        }

        payload_commu_state = PAYLOAD_STATE_RX;
        /* --- Accumulate --- */
        if ((current_offset + usb_data_rx.len) > sizeof(temp_buf))
        {
            /* Overflow protection: discard and reset */
            printf("ERR: buffer overflow, resetting\r\n");
            current_offset = 0;
            continue;
        }

        memcpy(&temp_buf[current_offset], usb_data_rx.usb_buff, usb_data_rx.len);
        current_offset += usb_data_rx.len;
        uint8_t check = KISS_IsFrameComplete(temp_buf, current_offset);
        
        /* --- O(1) completion check, no CRC yet --- */
        if (!check)
        {
            /* Frame not done yet, wait for more chunks */
            continue;
        }

        /* --- Frame boundary found: NOW do the full decode + CRC --- */
        // printf("Frame complete at offset %lu, unwrapping...\r\n", current_offset);

        kiss_status_t result = KISS_UnwrapFrame(temp_buf, current_offset,
                                                payload_content, &decoded_payload);

        current_offset = 0; /* Reset accumulator regardless of outcome */

        if (result != KISS_VALID_DATA)
        {
            printf("ERR: UnwrapFrame failed: %d\r\n", result);
            continue;
        }

        /* --- Process valid frame --- */

        if (decoded_payload.payload_id == KISS_PAYLOAD_ID_VR)
        {
            if (decoded_payload.type == KISS_FRAME_TYPE_IMAGE)
            {
                // printf("chunk: %d\r\n", current_chunk++);
                uint8_t  reply_frame[32];
                uint16_t reply_len = KISS_WrapFrame(KISS_PAYLOAD_ID_VR, KISS_PID_ACK, NULL, 0, 0x00, reply_frame, sizeof(reply_frame));
                CDC_Transmit_FS(reply_frame, reply_len);
                // decoded_payload.file_id
                fres = f_open(&fil,"0.jpg", FA_OPEN_APPEND | FA_WRITE);
                if (fres != FR_OK) {

                    printf("open to append error (%i)\r\n", fres);
                    continue;
                }
                unsigned int written = 0;
                f_write(&fil,(void*)decoded_payload.content,decoded_payload.content_len,&written);
                if (fres != FR_OK) {
                    printf("content append error (%i)\r\n", fres);
                    continue;
                }
                // printf("written %d\r\n",written);
                f_close(&fil);
                continue;
                // if (decoded_payload.content_len )
            }
            if (decoded_payload.pid == PID_VR_GS_RESPONSE_PING){
                uint32_t flag = osEventFlagsGet(payloadFlagHandle);

                if (flag & PAYLOAD_FLAG_PING){
                  osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_PING);
                  osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_RESPONSE_PING);
                }
              }
              else if (decoded_payload.pid == PID_VR_GS_RESPONSE_PI_STATUS){
                uint32_t flag = osEventFlagsGet(payloadFlagHandle);
                decoded_payload;
                if (flag & PAYLOAD_FLAG_REQUEST_STATUS){
                  osMessageQueuePut(payloadStatueQueueHandle,(void*)decoded_payload.content,0,1000);
                  osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_REQUEST_STATUS);
                  osEventFlagsSet(payloadFlagHandle,PAYLOAD_FLAG_RESPONSE_STATUS);
                }

            }
            else if (decoded_payload.pid == KISS_PID_ACK)
            {
                uint32_t flag = osEventFlagsGet(payloadFlagHandle);
                printf("payload_event_flag: %08lX\r\n", flag);

                if (flag & PAYLOAD_FLAG_POLL_CAPTURE)
                {
                    printf("Payload acks Capture\r\n");
                    osEventFlagsClear(payloadFlagHandle,PAYLOAD_FLAG_POLL_CAPTURE);
                    osEventFlagsSet(payloadFlagHandle, PAYLOAD_FLAG_IDLE);
                    payload_commu_state = PAYLOAD_STATE_IDLE;
                }

                if (flag & PAYLOAD_FLAG_IMAGE_REQUEST)
                {
                    printf("Payload acks Image Request\r\n");
                    osEventFlagsClear(payloadFlagHandle, PAYLOAD_FLAG_IMAGE_REQUEST);
                    osEventFlagsSet(payloadFlagHandle, PAYLOAD_FLAG_IMAGE_TRANSFER);

                    current_chunk = 0;
                    /* Set your image transfer state flag here */
                        //Open the file system
                    fres = f_mount(&FatFs, "", 1); //1=mount now
                    if (fres != FR_OK) {
                      printf("f_mount error (%i)\r\n", fres);
                      continue;
                    }
                    fres = f_open(&fil,"0.jpg",FA_CREATE_ALWAYS);
                    if (fres != FR_OK) {
                      printf("create file error (%i)\r\n", fres);
                      continue;
                    }
                    f_close(&fil);
                    printf("\033[0;32mOBC Starts Copy image from Payload\033[0m\r\n");
                    // osEventFlagsClear(payloadFlagHandle, PAYLOAD_FLAG_IMAGE_REQUEST);
                }
            }
            else if (decoded_payload.pid == KISS_VR_PID_IMAGE_DOWNLOAD_DONE){
              printf("\033[0;32mTransfer Image Done\033[0m\r\n");
              payload_commu_state = PAYLOAD_STATE_IDLE;
              osEventFlagsClear(payloadFlagHandle, PAYLOAD_FLAG_IMAGE_REQUEST | PAYLOAD_FLAG_IMAGE_TRANSFER);
              osEventFlagsSet(payloadFlagHandle, PAYLOAD_FLAG_IDLE);
              fres = f_mount(NULL, "", 0);
              if (fres != FR_OK) {
                printf("unmount error (%i)\r\n", fres);
                continue;
              }
            }
        }
    }
  /* USER CODE END usbTask */
}

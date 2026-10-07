#include "tasks/task_sensors.h"
#include "main.h"
#include "cmsis_os.h"

#include "tasks/task_shared.h"



void sensorQueryTask(void *argument)
{
  /* USER CODE BEGIN sensorQueryTask */

  eps_sensor_data_t _eps_sensors;

  tmp1075_t temp_sen = {
    .tmp1075_i2c_hal.hi2c = &hi2c4,
    .address = 0x48,
  };

 
  tmp1075_init(&temp_sen);

  for (;;)
  {
    // osEventFlagsWait(epsFlagHandle,EPS_FLAG_POLL_START,osFlagsWaitAny,osWaitForever);
    int32_t temp = 0;
    hal_status_t ret = tmp1075_read_temp(&temp_sen, &temp);
    if (ret != hal_ok)
    {
      printf("Read Temperature Error");
    }
    
    
    /* Perform Battery Temperatures Reads for 6 Channel */
    // for (int i = 0; i < EPS_NUM_TEMP_BATT;i++){
    eps_command_t cmd;
    uint8_t eps_data[EPS_BUF_SIZE] = {0};
    eps_get_all_kiss_command(&cmd);
    uint16_t decoded_len = EPS_Perform_Transaction(cmd.cmd,cmd.len,eps_data);

    uint16_t offset = 0;
    if (decoded_len != 0){
      osStatus_t os_ret = osMutexAcquire(sensorsMutexHandle,500);
      if (os_ret == osOK){
        eps_state = EPS_DATA_OK;
        osMutexRelease(sensorsMutexHandle);
      }
      // 1. Parse VI Sensors (8 Channels * 5 bytes = 40 bytes)
      for (uint8_t i = 0; i < EPS_NUM_VI_CHANNEL; i++) {
          if (offset + 5 > decoded_len) break; // Safety bounds check
          
          memcpy(&_eps_sensors.vi_sensor[i].voltage, &eps_data[offset], 2);
          offset += 2;
          memcpy(&_eps_sensors.vi_sensor[i].current, &eps_data[offset], 2);
          offset += 2;
          
          _eps_sensors.vi_sensor[i].channel = eps_data[offset++];
          _eps_sensors.vi_sensor[i].data_state = EPS_DATA_OK;
      }
  
      // 2. Parse Output Sensors (6 Channels * 5 bytes = 30 bytes)
      for (uint8_t i = 0; i < EPS_NUM_OUTPUT_CHANNEL; i++) {
          if (offset + 5 > decoded_len) break;
          
          memcpy(&_eps_sensors.output_sensor[i].voltage, &eps_data[offset], 2);
          offset += 2;
          memcpy(&_eps_sensors.output_sensor[i].current, &eps_data[offset], 2);
          offset += 2;
          
          _eps_sensors.output_sensor[i].channel = eps_data[offset++];
          _eps_sensors.output_sensor[i].data_state = EPS_DATA_OK;
      }
  
      // 3. Parse Output States (6 Channels * 2 bytes = 12 bytes)
      for (uint8_t i = 0; i < EPS_NUM_OUTPUT_CHANNEL; i++) {
          if (offset + 2 > decoded_len) break;
          
          _eps_sensors.output_state[i].status = eps_data[offset++];
          _eps_sensors.output_state[i].channel = eps_data[offset++];
          _eps_sensors.output_state[i].data_state = EPS_DATA_OK;
      }
  
      // 4. Parse Battery Temps (2 Channels * 5 bytes = 10 bytes)
      for (uint8_t i = 0; i < EPS_NUM_TEMP_BATT; i++) {
          if (offset + 5 > decoded_len) break;
          
          memcpy(&_eps_sensors.battery_temperature[i].temperature, &eps_data[offset], 4);
          offset += 4;
          
          _eps_sensors.battery_temperature[i].channel = eps_data[offset++];
          _eps_sensors.battery_temperature[i].data_state = EPS_DATA_OK;
      }
    }
    
    osStatus_t os_ret = osMutexAcquire(sensorsMutexHandle,500);
    if (os_ret == osOK){
      obc_sensors_data.temp = temp;
      // obc_sensors_data.datetime = datetime;
      eps_sensors_data = _eps_sensors;
      osMutexRelease(sensorsMutexHandle);
    }
    else{
      printf("Aquire OBC for Sending Sensor error\r\n");
    }

    osDelay(1000);

  }
  /* USER CODE END sensorQueryTask */
}

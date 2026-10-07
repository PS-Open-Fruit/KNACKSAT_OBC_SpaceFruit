#include "commu_helper.h"

uint8_t commu_temp_buff[COMMU_RX_SIZE];
uint8_t commu_data_buff[COMMU_BUF_SIZE];
uint16_t commu_offset = 0;
uint8_t commu_global_buff[COMMU_BUF_SIZE];
uint16_t commu_size = 0;
uint8_t commu_data_ready = 0;

osMessageQueueId_t communicationUartQueueHandle;
const osMessageQueueAttr_t communicationUartQueue_attributes = {
  .name = "communicationUartQueue"
};

osSemaphoreId_t commuSemaphoreHandle;
const osSemaphoreAttr_t commuSemaphoreAttr = {
  .name = "commuSemaphore"
};

osMutexId_t uartMutexHandle;
const osMutexAttr_t uartMutex_attributes = {
  .name = "uartMutex"
};

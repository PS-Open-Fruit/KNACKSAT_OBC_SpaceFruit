#include "tasks/task_comms.h"
#include "main.h"
#include "cmsis_os.h"

#include "tasks/task_shared.h"



void uartRx(void *argument)
{
  /* USER CODE BEGIN uartRx */
    uint16_t chunk_len = 0;
    /* Arm the very first receive — do it here, not in mainTask */
    HAL_UARTEx_ReceiveToIdle_IT(&COM_UART, commu_temp_buff, COMMU_RX_SIZE);
  /* Infinite loop */

    commu_state communication_state = COMMU_RX_IDLE;
    
    for(;;)
    {
        /* Block until the idle-line ISR signals a chunk arrived */
        osStatus_t status = osMessageQueueGet(communicationUartQueueHandle,
                                              &chunk_len, NULL, COMMU_RX_TIMEOUT);
        // if (status != osOK) continue;
        if (status == osErrorTimeout){
          if (communication_state == COMMU_RX_ONGOING){
            printf("Hanging RX Buffer for too long, Resetting\r\n");
            communication_state = COMMU_RX_IDLE;
            commu_offset = 0;
          }
          continue;
        }

        communication_state = COMMU_RX_ONGOING;

        // else if (status == osOK)
        /* --- Re-arm RX immediately so we don't miss the next bytes --- */
        HAL_UARTEx_ReceiveToIdle_IT(&COM_UART, commu_temp_buff, COMMU_RX_SIZE);

        /* --- Overflow guard --- */
        if ((commu_offset + chunk_len) > COMMU_BUF_SIZE)
        {
            printf("COMMU: buffer overflow, resetting\r\n");
            commu_offset = 0;
            continue;
        }

        /* --- Append chunk to accumulation buffer --- */
        memcpy(&commu_data_buff[commu_offset], commu_temp_buff, chunk_len);
        commu_offset += chunk_len;
        
        /* --- Debug print of what we have so far --- */
        printf("COMMU RX [%d bytes total]: ", commu_offset);
        for (int i = 0; i < commu_offset; i++) {
          printf("%02X ", commu_data_buff[i]);
        }
        printf("\r\n");
        
        /* --- Check if we have a complete KISS frame --- */
        if (!KISS_IsFrameComplete(commu_data_buff, commu_offset))
        {
            printf("COMMU: frame incomplete, waiting for more...\r\n");
            continue;
          }
          
          /* --- Complete frame: hand it off --- */
          printf("COMMU: complete KISS frame (%d bytes)\r\n", commu_offset);
          osMutexAcquire(uartMutexHandle,UART_MUTEX_TIMEOUT);
          for (int i = 0; i < commu_offset;i++){
            commu_global_buff[i] = commu_data_buff[i];
          }
          commu_size = commu_offset;
          commu_data_ready = 1;
          osMutexRelease(uartMutexHandle);  
          communication_state = COMMU_RX_IDLE;
          
        /* 
         * TODO: process commu_data_buff / commu_offset here.
         * e.g. KISS_UnwrapFrame(commu_data_buff, commu_offset, ...)
         * or copy into a queue for another task.
         */

        /* Reset accumulator for the next frame */
        commu_offset = 0;
  }
  /* USER CODE END uartRx */
}

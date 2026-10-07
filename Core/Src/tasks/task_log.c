#include "tasks/task_log.h"
#include "main.h"
#include "cmsis_os.h"

#include "tasks/task_shared.h"



void logTask(void *argument)
{
  /* USER CODE BEGIN logTask */
  uint8_t ch = 0;
  /* Infinite loop */
  for(;;)
  {
    osMessageQueueGet(printQueueHandle,&ch,NULL,osWaitForever);
    // HAL_UART_Transmit_IT(&huart3, (uint8_t *)&ch, 1);
    HAL_UART_Transmit(&huart5, (uint8_t *)&ch, 1, 0xFFFF);
    // osDelay(1);
  }
  /* USER CODE END logTask */
}

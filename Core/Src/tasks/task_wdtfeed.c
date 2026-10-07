#include "tasks/task_wdtfeed.h"
#include "main.h"
#include "cmsis_os.h"

#include "tasks/task_shared.h"



void wdtFeedTask(void *argument)
{
  /* USER CODE BEGIN wdtFeedTask */
  /* Infinite loop */
  for (;;)
  {
    if (HAL_IWDG_Refresh(&hiwdg) != HAL_OK)
    {
      printf("IWDT Error\r\n");
    }
    // printf("IWDG Still triggering\r\n");
    osDelay(400);
  }
  /* USER CODE END wdtFeedTask */
}

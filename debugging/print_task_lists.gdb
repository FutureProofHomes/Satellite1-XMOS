define print_suspended_tasks
  printf "=== xSuspendedTaskList ===\n"
  set $susp = &xSuspendedTaskList
  set $item = $susp->xListEnd.pxNext
  while ($item != &$susp->xListEnd)
    if $item->pvOwner != 0
      set $tcb = (TCB_t *)$item->pvOwner
      printf "Task: %s | TCB: %p\n", $tcb->pcTaskName, $tcb
    else
      printf "NULL pvOwner at ListItem: %p\n", $item
    end
    set $item = $item->pxNext
  end
end

define print_highest_ready_tasks
  printf "\n=== pxReadyTasksLists (highest priority non-empty) ===\n"
  # configMAX_PRIORITIES - 1
  set $i = 31 
  while $i >= 0
    set $list = &pxReadyTasksLists[$i]
    p $list
    if $list->uxNumberOfItems > 0
      printf "Found ready list with priority %d len: %d\n", $i, $list->uxNumberOfItems
      set $item = $list->xListEnd.pxNext
      p $item
      p *$item
      while ($item != &$list->xListEnd)
        if $item->pvOwner != 0
          set $tcb = (TCB_t *)$item->pvOwner
          printf "Task: %s | TCB: %p\n", $tcb->pcTaskName, $tcb
        else
          printf "NULL pvOwner at ListItem: %p\n", $item
        end
        set $item = $item->pxNext
      end
    end
    set $i = $i - 1
  end
end


print_suspended_tasks
print_highest_ready_tasks
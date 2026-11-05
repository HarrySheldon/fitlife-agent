import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { Modal } from './Modal'

it('keeps focus inside the top modal, handles Escape once and restores the trigger', async () => {
  const parent=vi.fn(), closed=vi.fn()
  function Example() {
    const [open,setOpen]=useState(false)
    return <div onKeyDown={parent}><button onClick={()=>setOpen(true)}>Open task</button>
      {open ? <Modal label="Task" onClose={()=>{closed();setOpen(false)}}>
        <button>First</button><button disabled>Disabled</button><input aria-label="Last" />
        <details><summary>Technical details</summary><pre>Raw values</pre></details>
      </Modal>:null}</div>
  }
  render(<Example />)
  const trigger=screen.getByRole('button',{name:'Open task'})
  trigger.focus(); fireEvent.click(trigger)
  const first=screen.getByRole('button',{name:'First'}), last=screen.getByRole('textbox',{name:'Last'})
  const summary=screen.getByText('Technical details')
  expect(first).toHaveFocus()
  expect(screen.getByRole('dialog')).toHaveAttribute('open')
  fireEvent.keyDown(first,{key:'Tab',shiftKey:true}); expect(summary).toHaveFocus()
  // Interior Tab must retain the browser's natural order, not jump to the start.
  last.focus()
  expect(fireEvent.keyDown(last,{key:'Tab'})).toBe(true)
  summary.focus()
  fireEvent.keyDown(summary,{key:'Tab'}); expect(first).toHaveFocus()
  parent.mockClear()
  fireEvent.keyDown(first,{key:'Escape'})
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(closed).toHaveBeenCalledTimes(1)
  expect(parent).not.toHaveBeenCalled()
  expect(trigger).toHaveFocus()
  expect(document.body.style.overflow).not.toBe('hidden')
})

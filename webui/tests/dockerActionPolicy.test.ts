import {afterEach,expect,it,vi} from 'vitest'
import {confirmAction,promptConfirmation} from '../src/util/actionConfirmation'
import {withOnlinePlayerGuard} from '../src/api/client'
afterEach(()=>{vi.unstubAllEnvs();vi.restoreAllMocks()})
it('runs Docker actions without browser dialogs or a player verification retry',async()=>{
 vi.stubEnv('VITE_DST_EDITION','docker')
 const confirm=vi.spyOn(window,'confirm'),prompt=vi.spyOn(window,'prompt'),action=vi.fn(async(force:boolean)=>force)
 expect(confirmAction('Restart?')).toBe(true)
 expect(promptConfirmation('RESTORE','Type RESTORE')).toBe('RESTORE')
 expect(await withOnlinePlayerGuard(action)).toBe(true)
 expect(action).toHaveBeenCalledExactlyOnceWith(true)
 expect(confirm).not.toHaveBeenCalled();expect(prompt).not.toHaveBeenCalled()
})
it('preserves Windows dialog and initial player verification behavior',async()=>{
 vi.stubEnv('VITE_DST_EDITION','windows')
 vi.spyOn(window,'confirm').mockReturnValue(false);vi.spyOn(window,'prompt').mockReturnValue(null)
 expect(confirmAction('Restart?')).toBe(false);expect(promptConfirmation('RESTORE','Type RESTORE')).toBeNull()
 const action=vi.fn(async(force:boolean)=>force)
 expect(await withOnlinePlayerGuard(action)).toBe(false)
 expect(action).toHaveBeenCalledExactlyOnceWith(false)
})

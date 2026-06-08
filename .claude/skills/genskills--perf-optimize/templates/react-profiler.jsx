import { Profiler } from 'react';

function onRender(id, phase, actualDuration, baseDuration, startTime, commitTime) {
  // id: component tree id
  // phase: "mount" or "update"
  // actualDuration: time spent rendering this update
  // baseDuration: estimated time to render entire subtree without memoization
  console.log(`${id} ${phase}: ${actualDuration.toFixed(1)}ms (base: ${baseDuration.toFixed(1)}ms)`);
}

<Profiler id="Navigation" onRender={onRender}>
  <Navigation />
</Profiler>

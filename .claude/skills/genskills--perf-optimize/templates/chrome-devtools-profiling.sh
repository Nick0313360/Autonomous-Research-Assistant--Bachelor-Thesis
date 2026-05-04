# Start Node.js with inspector
node --inspect=0.0.0.0:9229 app.js

# Programmatic CPU profiling via Chrome DevTools Protocol
node -e "
const inspector = require('inspector');
const session = new inspector.Session();
session.connect();
session.post('Profiler.enable');
session.post('Profiler.start');
// ... run workload ...
setTimeout(() => {
  session.post('Profiler.stop', (err, { profile }) => {
    require('fs').writeFileSync('profile.cpuprofile', JSON.stringify(profile));
    // Open in Chrome DevTools → Performance tab → Load profile
  });
}, 10000);
"

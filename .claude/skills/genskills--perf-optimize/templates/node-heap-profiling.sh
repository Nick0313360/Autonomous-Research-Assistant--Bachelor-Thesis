# Take a heap snapshot programmatically
node -e "const v8 = require('v8'); const fs = require('fs'); fs.writeFileSync('heap.heapsnapshot', v8.writeHeapSnapshot());"

# Run with heap size tracking
node --max-old-space-size=4096 --trace-gc app.js

# Use clinic.js for memory analysis
npx clinic heapprofile -- node app.js
npx clinic doctor -- node app.js

# Generate heap snapshot via Chrome DevTools protocol
node --inspect app.js
# Then in Chrome: chrome://inspect → take heap snapshot → compare snapshots

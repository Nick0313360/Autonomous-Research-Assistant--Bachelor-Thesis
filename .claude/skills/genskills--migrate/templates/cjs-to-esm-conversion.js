// Before (CJS)
const path = require('path');
const { readFile } = require('fs/promises');
const myModule = require('./myModule');
module.exports = { foo, bar };
module.exports.default = baz;

// After (ESM)
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import myModule from './myModule.js';  // .js extension required!
export { foo, bar };
export default baz;

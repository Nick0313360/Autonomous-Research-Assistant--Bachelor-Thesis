// csp.config.ts
export const cspDirectives = {
  defaultSrc: ["'self'"],
  scriptSrc: ["'self'", "'strict-dynamic'"],
  styleSrc: ["'self'", "'unsafe-inline'"],  // tighten after setup
  imgSrc: ["'self'", "data:", "https:"],
  connectSrc: ["'self'"],
  fontSrc: ["'self'"],
  objectSrc: ["'none'"],
  frameAncestors: ["'none'"],
  upgradeInsecureRequests: [],
};

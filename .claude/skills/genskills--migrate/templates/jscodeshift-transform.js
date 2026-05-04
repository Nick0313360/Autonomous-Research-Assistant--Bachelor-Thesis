// transform-require-to-import.js
module.exports = function transformer(fileInfo, api) {
  const j = api.jscodeshift;
  const root = j(fileInfo.source);

  // Find all require() calls
  root.find(j.CallExpression, {
    callee: { name: 'require' },
  }).forEach(path => {
    const parent = path.parent.node;
    if (parent.type === 'VariableDeclarator' && parent.id.type === 'Identifier') {
      const importName = parent.id.name;
      const source = path.node.arguments[0].value;

      // Replace: const foo = require('bar')
      // With:    import foo from 'bar'
      j(path.parent.parent).replaceWith(
        j.importDeclaration(
          [j.importDefaultSpecifier(j.identifier(importName))],
          j.literal(source)
        )
      );
    }
  });

  return root.toSource({ quote: 'single' });
};

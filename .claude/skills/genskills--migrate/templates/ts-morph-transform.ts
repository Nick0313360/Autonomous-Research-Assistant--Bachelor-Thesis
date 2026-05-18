import { Project, SyntaxKind } from 'ts-morph';

const project = new Project({ tsConfigFilePath: 'tsconfig.json' });

for (const sourceFile of project.getSourceFiles()) {
  // Example: rename all instances of an interface
  sourceFile.getInterfaces().forEach(iface => {
    if (iface.getName() === 'OldName') {
      iface.rename('NewName'); // Renames all references too
    }
  });

  // Example: add return types to all functions missing them
  sourceFile.getFunctions().forEach(fn => {
    if (!fn.getReturnTypeNode()) {
      const returnType = fn.getReturnType().getText();
      fn.setReturnType(returnType);
    }
  });
}

project.saveSync();

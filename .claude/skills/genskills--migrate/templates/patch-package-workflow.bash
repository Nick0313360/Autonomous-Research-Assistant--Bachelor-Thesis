# 1. Make your fix directly in node_modules/<package>/
# 2. Generate the patch
npx patch-package <package-name>
# Creates patches/<package-name>+<version>.patch

# 3. Add to postinstall
# package.json:
{
  "scripts": {
    "postinstall": "patch-package"
  }
}

# 4. Commit the patches/ directory
# 5. Remove the patch once the upstream fix is released

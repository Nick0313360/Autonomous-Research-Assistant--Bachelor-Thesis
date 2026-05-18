---
name: genskills:storybook
description: >
  Generate Storybook stories for UI components with variants, controls, and docs.
  Triggers on: "storybook", "generate stories", "add story", "component stories",
  "storybook setup".
user-invocable: true
argument-hint: "[component-path or 'setup' or 'all'] [--format csf3|csf2] [--with-tests] [--with-docs]"
allowed-tools: "Read, Write, Edit, Grep, Glob, Bash(npm *), Bash(npx *), Bash(pnpm *), Bash(git diff*)"
genskills-version: "1.3.0"
genskills-category: "documentation"
genskills-depends: []
---

# Storybook

Generate Storybook stories for UI components.

## Process

### Step 0: Load Context
- Check `CLAUDE.md` for component documentation conventions
- Check `${CLAUDE_SKILL_DIR}/_config.json` for preferences
- Check for existing `.storybook/` configuration directory
- Find existing story files to match established patterns (format, naming, structure)

### Step 1: Parse Arguments
Parse `$ARGUMENTS`:
- First positional: component path, "setup", or "all"
- `--format`: story format - "csf3" (default, object-based) | "csf2" (arrow function)
- `--with-tests`: include Storybook interaction tests (play functions)
- `--with-docs`: include MDX documentation page alongside stories
- `--changed`: generate stories for recently changed components (`git diff --name-only HEAD~1`)
- `--dry-run`: list components that need stories without generating

### Step 2: Setup (if `setup` or Storybook not installed)

Check if Storybook is already configured:
```bash
ls .storybook/main.ts .storybook/main.js 2>/dev/null
```

If not installed:
```bash
npx storybook@latest init
```

If already initialized, verify configuration supports the project:

| Check | How |
|---|---|
| Framework addon | `.storybook/main.ts` → `framework` field matches project (React, Vue, Svelte, Angular, Web Components) |
| TypeScript | `.storybook/main.ts` → `typescript` config present |
| CSS/Styling | Tailwind, CSS modules, styled-components, Emotion configured in preview |
| Path aliases | `webpackFinal` or `viteFinal` matches tsconfig `paths` |
| Theme provider | Global decorators in `.storybook/preview.ts` wrap stories with theme/i18n |
| Addons | Essential addons installed: `@storybook/addon-essentials`, a11y addon |

**Recommend addons if missing:**
```bash
npm install -D @storybook/addon-a11y           # Accessibility checks
npm install -D @storybook/addon-interactions    # Interaction testing
npm install -D @storybook/addon-coverage        # Coverage reporting
```

### Step 3: Discover Components (if `all`)
Find components that need stories:

```bash
# Find all component files
# Glob: **/*.tsx, **/*.vue, **/*.svelte (excluding test/story files)

# Find existing stories
# Glob: **/*.stories.tsx, **/*.stories.ts, **/*.stories.mdx
```

**Missing stories = component files without corresponding story files.**

Report:
```
Found N components, M have stories, K need stories:
- src/components/Button.tsx - ✓ has story
- src/components/Modal.tsx - ✗ needs story
- src/components/DataTable.tsx - ✗ needs story
```

### Step 4: Analyze Component
For each target component:

**1. Extract component API:**
- Props interface/type with defaults, required/optional, JSDoc descriptions
- Component variants (via props like `variant`, `size`, `color`, `intent`)
- Slots/children patterns (React children, Vue slots, Svelte slots)
- Event handlers (`onClick`, `onChange`, `onSubmit`, custom events)
- Ref forwarding (`forwardRef`, `useImperativeHandle`)

**2. Identify states:**
- Loading/skeleton state
- Error state
- Empty state
- Disabled state
- Active/selected state
- Hover/focus states (for interaction tests)

**3. Find existing usage:**
- Search codebase for how the component is used
- Identify common prop combinations
- Typical children/content patterns
- Context providers needed (theme, i18n, router, auth)

**4. Check related components:**
- Compound components (`Tabs` + `Tab` + `TabPanel`)
- Associated types and enums
- Parent/child relationships

### Step 5: Generate Story File

Create `<ComponentName>.stories.tsx` (or `.stories.ts` for non-JSX):

**CSF3 format (default - recommended):**
```typescript
import type { Meta, StoryObj } from '@storybook/react';
import { expect, fn, userEvent, within } from '@storybook/test';
import { ComponentName } from './ComponentName';

const meta = {
  title: 'Components/ComponentName',
  component: ComponentName,
  tags: ['autodocs'],
  parameters: {
    layout: 'centered',  // or 'padded' or 'fullscreen'
    docs: {
      description: {
        component: 'Brief description of the component and its purpose.',
      },
    },
  },
  argTypes: {
    variant: {
      control: 'select',
      options: ['primary', 'secondary', 'outline', 'ghost'],
      description: 'Visual style variant',
      table: { defaultValue: { summary: 'primary' } },
    },
    size: {
      control: 'select',
      options: ['sm', 'md', 'lg'],
      description: 'Size of the component',
      table: { defaultValue: { summary: 'md' } },
    },
    disabled: {
      control: 'boolean',
      description: 'Whether the component is disabled',
    },
    onClick: { action: 'clicked' },
  },
  args: {
    children: 'Button Text',
    variant: 'primary',
    size: 'md',
    onClick: fn(),
  },
} satisfies Meta<typeof ComponentName>;

export default meta;
type Story = StoryObj<typeof meta>;

// === Default ===
export const Default: Story = {};

// === Variants ===
export const Primary: Story = {
  args: { variant: 'primary' },
};

export const Secondary: Story = {
  args: { variant: 'secondary' },
};

export const Outline: Story = {
  args: { variant: 'outline' },
};

// === States ===
export const Disabled: Story = {
  args: { disabled: true },
};

export const Loading: Story = {
  args: { loading: true },
};

// === Edge Cases ===
export const LongText: Story = {
  args: { children: 'This is a very long button label that might overflow' },
};

export const Empty: Story = {
  args: { children: '' },
};

// === Composition ===
export const AllVariants: Story = {
  render: (args) => (
    <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
      <ComponentName {...args} variant="primary">Primary</ComponentName>
      <ComponentName {...args} variant="secondary">Secondary</ComponentName>
      <ComponentName {...args} variant="outline">Outline</ComponentName>
      <ComponentName {...args} variant="ghost">Ghost</ComponentName>
    </div>
  ),
};

export const AllSizes: Story = {
  render: (args) => (
    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
      <ComponentName {...args} size="sm">Small</ComponentName>
      <ComponentName {...args} size="md">Medium</ComponentName>
      <ComponentName {...args} size="lg">Large</ComponentName>
    </div>
  ),
};
```

**With interaction tests (`--with-tests`):**
```typescript
export const ClickTest: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole('button');
    await userEvent.click(button);
    await expect(args.onClick).toHaveBeenCalledOnce();
  },
};

export const KeyboardNavigation: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole('button');
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await userEvent.keyboard('{Enter}');
  },
};
```

**Story generation rules:**
- One story per meaningful variant/state combination (not every permutation)
- Include `Default` story with sensible defaults
- Use `argTypes` for all controllable props with descriptions
- Use `fn()` (Storybook 8+) or `action()` for event handlers
- Add composition stories showing variants side-by-side
- Include edge cases: long text, empty content, overflow, loading, error
- Add decorators for required context (theme, i18n, router providers)
- Use `satisfies Meta` for type safety (Storybook 7+)
- Use `tags: ['autodocs']` for auto-generated documentation

### Step 6: Handle Special Cases

**Components requiring providers:**
```typescript
const meta = {
  decorators: [
    (Story) => (
      <ThemeProvider theme={defaultTheme}>
        <RouterProvider>
          <Story />
        </RouterProvider>
      </ThemeProvider>
    ),
  ],
};
```

**Compound components:**
```typescript
export const TabsExample: Story = {
  render: () => (
    <Tabs defaultValue="tab1">
      <TabList>
        <Tab value="tab1">Tab 1</Tab>
        <Tab value="tab2">Tab 2</Tab>
      </TabList>
      <TabPanel value="tab1">Content 1</TabPanel>
      <TabPanel value="tab2">Content 2</TabPanel>
    </Tabs>
  ),
};
```

**Form components:**
```typescript
export const WithValidation: Story = {
  args: { error: 'This field is required' },
};

export const InForm: Story = {
  render: (args) => (
    <form onSubmit={(e) => e.preventDefault()}>
      <ComponentName {...args} />
      <button type="submit">Submit</button>
    </form>
  ),
};
```

**Responsive components:**
```typescript
export const Mobile: Story = {
  parameters: {
    viewport: { defaultViewport: 'mobile1' },
  },
};
```

**Dark mode:**
```typescript
export const DarkMode: Story = {
  parameters: {
    backgrounds: { default: 'dark' },
  },
  decorators: [(Story) => <div className="dark"><Story /></div>],
};
```

### Step 7: Generate MDX Docs (if --with-docs)
Create `<ComponentName>.mdx` alongside the story:

```mdx
import { Meta, Canvas, Controls, Story } from '@storybook/blocks';
import * as ComponentStories from './ComponentName.stories';

<Meta of={ComponentStories} />

# ComponentName

Brief description of the component, when to use it, and design guidelines.

## Usage

```tsx
import { ComponentName } from '@/components/ComponentName';

<ComponentName variant="primary" size="md">
  Click me
</ComponentName>
```

## Variants

<Canvas of={ComponentStories.AllVariants} />

## Props

<Controls />

## Accessibility

- Keyboard navigable via Tab and Enter/Space
- Screen reader announces button label
- Disabled state communicated via `aria-disabled`

## Design Guidelines

- Use Primary for main actions, Secondary for alternative actions
- Limit button text to 2-3 words where possible
```

### Step 8: Verify
```bash
npx storybook build --quiet 2>&1    # Check for build errors
```

If errors occur:
- Fix import paths, missing providers, type errors
- Re-verify after fixes

### Step 9: Report
```
## Stories Generated

### Components
| Component | Stories | Tests | Docs |
|---|---|---|---|
| Button | 8 stories | 2 play tests | ✓ MDX |
| Modal | 5 stories | 1 play test | - |
| DataTable | 6 stories | - | ✓ MDX |

### Story Types Created
| Type | Count |
|---|---|
| Default | N |
| Variants | N |
| States | N |
| Edge cases | N |
| Compositions | N |
| Interaction tests | N |

### Controls Configured
- variant: select - N options
- size: select - N options
- disabled: boolean
- onClick: action

### Verification
- Storybook build: ✓ passed / ✗ errors (details)

### Usage
$ npx storybook dev           # Start dev server
$ npx storybook build         # Build static site
$ npx test-storybook          # Run interaction tests

### Follow-up
- Run `/genskills:accessibility-audit` on components for a11y issues
- Run `/genskills:test-generator` for unit tests alongside stories
- Deploy Storybook to Chromatic or GitHub Pages for team access
```

## Configuration
Check `${CLAUDE_SKILL_DIR}/_config.json` for user preferences:
- `storyDir`: "adjacent" | "__stories__" - where to place story files (default: "adjacent")
- `format`: "csf3" | "csf2" - story format (default: "csf3")
- `includeA11y`: boolean - add a11y addon checks (default: true)
- `includePlayTests`: boolean - add interaction tests (default: false)
- `includeDocs`: boolean - generate MDX documentation (default: false)
- `includeResponsive`: boolean - add mobile/tablet viewport stories (default: false)
- `includeDarkMode`: boolean - add dark mode variant stories (default: false)
- `layout`: "centered" | "padded" | "fullscreen" - default story layout (default: "centered")

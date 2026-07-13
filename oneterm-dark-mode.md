---
type: how-to
tags: [oneterm, frontend, vue, ant-design]
created: 2026-06-26
last_verified: 2026-06-26
status: current
---

# Adding Full Dark Mode to OneTerm (Vue 2 + Ant Design Vue 1.x)

**Date:** 2026-06-26  
**Repo:** [txtsamu/oneterm](https://github.com/txtsamu/oneterm) (forked from veops/oneterm)  
**Stack:** Vue 2, Ant Design Vue 1.x (ANT Design 3.x base), LESS, vxe-table, echarts

---

## 1. Fork and clone

```bash
gh repo fork veops/oneterm --clone=true --fork-name oneterm
```

---

## 2. Understand the frontend build system

The UI lives in `oneterm-ui/`. Key files:

| File | Role |
|------|------|
| `src/style/static.less` | All custom color/layout variables — injected into every component via `style-resources-loader` |
| `src/style/global.less` | Imports antd.less + static.less; global layout overrides |
| `src/style/index.less` | Entry point, just imports global.less |
| `vue.config.js` | `modifyVars` block overrides ANT Design LESS variables at compile time |

The `style-resources-loader` plugin (configured in `vue.config.js`) injects `static.less` into every `.vue` component's `<style lang="less">` block — so all LESS variables defined there are available everywhere without explicit imports.

---

## 3. Why `modifyVars` alone isn't enough for ANT Design 3.x

ANT Design Vue 1.x is based on ANT Design 3.x. Unlike ANT Design 4.x, version 3.x does **not** have a built-in dark theme (`antd.dark.less` only exists reliably in 1.7.0+, and even then it is incomplete). Many component styles have **hardcoded** `rgba(0,0,0,0.65)` text and `#ffffff`/`#f5f5f5` backgrounds that `modifyVars` cannot reach because they are literal values, not variable references.

The full approach requires three layers:

1. **`modifyVars`** — overrides the LESS variables that ANT Design 3.x does parameterise (body-background, component-background, input-bg, etc.)
2. **`static.less` variable overrides** — overrides the app's own custom tokens
3. **`dark-patch.less`** — explicit CSS overrides for every antd component class that still has hardcoded light colors

---

## 4. Update `static.less` variables

Change every color token from light to dark equivalents:

```less
// primary-color_3–7 used as "tinted primary" backgrounds throughout the app
@primary-color_3: #162135;   // was #ebeff8
@primary-color_4: #111e2e;   // was #e1efff
@primary-color_5: #0d1729;   // was #f0f5ff
@primary-color_6: #0a1020;   // was #f9fbff
@primary-color_7: #1a1a1a;   // was #f7f8fa

// Neutral text scale — flip light→dark
@text-color_1: #e8e8e8;   // was #1d2129
@text-color_2: #a6a6a6;   // was #4e5969
@text-color_3: #737373;   // was #86909c
@text-color_4: #595959;   // was #a5a9bc
@text-color_5: #3a3a3a;   // was #cacdd9
@text-color_6: #303030;   // was #e4e7ed (border shade)
@text-color_7: #1f1f1f;   // was #f0f1f5 (lightest bg shade)

@border-color-base: #303030;
@component-background: #1f1f1f;
@layout-content-background: #141414;
@layout-header-background: #1f1f1f;
@layout-header-font-color: #e8e8e8;
@layout-sidebar-color: #1f1f1f;
@layout-sidebar-sub-color: #141414;
@layout-sidebar-selected-color: #162135;
```

---

## 5. Update `vue.config.js` modifyVars

These override ANT Design 3.x's own LESS variables at compile time:

```js
modifyVars: {
  'primary-color': '#2f54eb',
  'body-background': '#141414',
  'component-background': '#1f1f1f',
  'layout-body-background': '#141414',
  'layout-header-background': '#1f1f1f',
  'layout-sider-background': '#1f1f1f',
  'border-color-base': '#303030',
  'border-color-split': '#303030',
  'item-hover-bg': '#262626',
  'text-color': 'rgba(255, 255, 255, 0.85)',
  'text-color-secondary': 'rgba(255, 255, 255, 0.45)',
  'disabled-color': 'rgba(255, 255, 255, 0.25)',
  'input-bg': '#262626',
  'select-background': '#262626',
  'tooltip-bg': '#434343',
  'popover-bg': '#2d2d2d',
  'modal-content-bg': '#1f1f1f',
  'card-background': '#1f1f1f',
  'table-bg': '#1f1f1f',
  'table-header-bg': '#262626',
  'table-row-hover-bg': '#262626',
  'table-selected-row-bg': '#2a3554',
  'menu-dark-bg': '#1f1f1f',
  'menu-dark-submenu-bg': '#141414',
},
```

---

## 6. Batch-replace hardcoded colors in source files

Many Vue component `<style>` blocks have hardcoded light colors that bypass both `modifyVars` and LESS variables. Use `sed` to replace them all at once:

```bash
# Hardcoded white backgrounds
find src \( -name "*.vue" -o -name "*.less" \) -exec sed -i \
  -e 's/background-color: #fff;/background-color: #1f1f1f;/g' \
  -e 's/background-color: #ffffff;/background-color: #1f1f1f;/g' \
  -e 's/background: #fff;/background: #1f1f1f;/g' \
  -e 's/background: #ffffff;/background: #1f1f1f;/g' \
  {} \;

# Light gray backgrounds
find src \( -name "*.vue" -o -name "*.less" \) -exec sed -i \
  -e 's/background-color: #fafafa;/background-color: #262626;/g' \
  -e 's/background-color: #f5f5f5;/background-color: #262626;/g' \
  -e 's/background-color: #f0f2f5;/background-color: #1a1a1a;/g' \
  {} \;

# Hardcoded dark text (invisible on dark backgrounds)
find src \( -name "*.vue" -o -name "*.less" \) -exec sed -i \
  -e 's/color: rgba(0, 0, 0, \.85)/color: rgba(255, 255, 255, 0.85)/g' \
  -e 's/color: rgba(0, 0, 0, 0\.85)/color: rgba(255, 255, 255, 0.85)/g' \
  -e 's/color: rgba(0, 0, 0, 0\.45)/color: rgba(255, 255, 255, 0.45)/g' \
  -e 's/color: rgba(0, 0, 0, 0\.5)/color: rgba(255, 255, 255, 0.5)/g' \
  -e 's/color: #1d2129;/color: @text-color_1;/g' \
  -e 's/color: #4e5969;/color: @text-color_2;/g' \
  -e 's/color: #000;/color: @text-color_1;/g' \
  {} \;
```

**Gotcha: case sensitivity.** The sed patterns are case-sensitive. Some components used uppercase hex (`#F9FBFF`, `#EBEFF8`, `#E1EFFF`). Run a second pass for uppercase variants, or use LESS variable references instead:

```bash
find src \( -name "*.vue" -o -name "*.less" \) -exec sed -i \
  -e 's/background-color: #F9FBFF/background-color: @primary-color_6/g' \
  -e 's/background-color: #EBEFF8/background-color: @primary-color_3/g' \
  -e 's/background-color: #E1EFFF/background-color: @primary-color_4/g' \
  -e 's/border-color: #E4E7ED/border-color: @border-color-base/g' \
  {} \;
```

---

## 7. Add `dark-patch.less` for antd components with hardcoded colors

Create `src/style/dark-patch.less` with explicit CSS overrides for every antd component class. This is necessary because ANT Design 3.x has ~200+ hardcoded `rgba(0,0,0,x)` and `#fff` values in its compiled output that `modifyVars` cannot reach.

Import it in `src/style/index.less`:

```less
@import "./global.less";
@import "./dark-patch.less";
```

The patch file defines local shorthand variables for clarity:

```less
@dp-bg-0: #141414;   // page base
@dp-bg-1: #1f1f1f;   // surface (cards, panels)
@dp-bg-2: #262626;   // elevated (inputs, hover rows)
@dp-bg-3: #2d2d2d;   // floating (dropdowns, popovers)
@dp-text-1: rgba(255, 255, 255, 0.85);
@dp-text-2: rgba(255, 255, 255, 0.45);
@dp-text-3: rgba(255, 255, 255, 0.25);
@dp-border: #303030;
@dp-hover: #2a3554;  // selected row / active item
```

Cover every major component: table, card, modal, drawer, select, dropdown, input, form, tabs, collapse, list, tree, pagination, menu, tooltip, popover, date/time picker, transfer, descriptions, alert, tag, steps, upload, checkbox, radio, switch, slider, cascader, notification, message, statistic, progress, divider, breadcrumb, typography.

---

## 8. vxe-table needs its own dark overrides

The assets page uses `<ops-table>` which wraps `vxe-table` — a completely separate component from `ant-table`. The `dark-patch.less` antd overrides don't affect it. Add explicit overrides targeting vxe-table's CSS classes:

```less
.vxe-table--render-default {
  background: @dp-bg-1;
  color: @dp-text-1;

  .vxe-table--header-wrapper { background: @dp-bg-2 !important; }
  .vxe-header--column {
    background: @dp-bg-2 !important;
    color: @dp-text-1 !important;
    border-color: @dp-border !important;
  }
  .vxe-body--row { background: @dp-bg-1; color: @dp-text-1; }
  .vxe-body--row.row--hover { background: @dp-bg-2 !important; }
  .vxe-body--row.row--checked { background: @dp-hover !important; }
  .vxe-body--column {
    background: transparent !important;
    color: @dp-text-1 !important;
    border-color: @dp-border !important;
  }
  // border-image trick used by vxe for full-border mode
  &.border--full .vxe-body--column,
  &.border--full .vxe-header--column {
    background-image: linear-gradient(@dp-border, @dp-border),
                      linear-gradient(@dp-border, @dp-border) !important;
  }
}
```

Also override `.vxe-pager` for dark pagination controls.

---

## 9. Fix hardcoded colors in JavaScript (echarts, chart options)

Chart libraries like echarts take color values as JavaScript strings — LESS variables have no effect on them. Find and fix manually:

```js
// assetType.vue — center number of the donut chart
graphic: {
  style: {
    fill: '#e8e8e8',   // was '#000'
    fontSize: 38,
  }
}
```

Do a sweep for all JS-context color literals:

```bash
find src -name "*.vue" -exec sed -i \
  -e "s/fill: '#000'/fill: '#e8e8e8'/g" \
  -e "s/color: '#000'/color: '#e8e8e8'/g" \
  {} \;
```

For echarts `legend`, `tooltip`, and `axisLabel` text you may also need to set `textStyle: { color: '#a6a6a6' }` per chart instance — check each chart component individually.

---

## 10. Dark color palette reference

| Token | Value | Used for |
|-------|-------|---------|
| `#141414` | Page body, deepest background |
| `#1f1f1f` | Cards, panels, surface |
| `#262626` | Inputs, elevated surfaces, hover rows |
| `#2d2d2d` | Dropdowns, popovers, floating layers |
| `#2a3554` | Selected rows, active items |
| `#303030` | Borders, dividers |
| `rgba(255,255,255,0.85)` | Primary text |
| `rgba(255,255,255,0.45)` | Secondary text, placeholders |
| `rgba(255,255,255,0.25)` | Disabled text |
| `#2f54eb` | Primary accent (unchanged) |

This is the standard Material Design dark surface palette adapted for a blue primary accent.

# KNOWNEST Design System

## Visual World

KNOWNEST uses a quiet local-workbench language: warm paper white surfaces, deep gray-green utility surfaces, hairline dividers, and restrained state colors. The visual reference is a Chinese knowledge desk, not a generic centered login card.

## Typography

Chinese serif display type establishes product voice for page titles and the KNOWNEST lockup. System CJK sans-serif is used for labels, form controls, descriptions, and status text. Monospace is reserved for API paths and operational labels.

## Color Roles

- `#f5f2e9`: page ground
- `#edf0e7`: brand rail
- `#faf8f1`: task surface
- `#4f705f`: primary action and ready state
- `#d8d2c5`: structural divider
- `#b36551`: unavailable and error state
- `#bd9657`: checking state

## Signature

Every operational surface makes state legible with fixed rows, explicit labels, and real endpoint names. Status never relies on color alone: the text label and recovery action remain visible.

## Responsive Behavior

Desktop uses a three-column workbench. At medium widths the status rail moves below the form. At narrow widths the brand, form, and status sections stack vertically with no horizontal scroll; all controls remain keyboard and touch accessible.

## Login Surface

The login surface is defined in `.impeccable/surfaces/frontend-src-app-vue.md`. Its primary task is login or first-run setup through the existing runtime authentication API.

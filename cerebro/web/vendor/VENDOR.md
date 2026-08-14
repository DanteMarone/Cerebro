# Vendored Front-End Dependencies

Per §Front End in `SLICE_1.md`: No npm, no bundler, no CDN. All client-side runtime libraries are vendored as literal ESM files with SHA-256 integrity verification.

## Dependencies

### Preact
- **Package**: `preact`
- **Version**: `10.23.2`
- **License**: MIT
- **File**: [`preact.mjs`](preact.mjs)
- **SHA-256**: `c2e05710940de1c45081786322a2d380d202d16c2c97cf3ebb5a02381b2e3c69`
- **Description**: Fast 3kB alternative to React with standard ES module exports (`h`, `render`, `useState`, `useEffect`, `useRef`, `useCallback`, `useMemo`).

### HTM
- **Package**: `htm`
- **Version**: `3.1.1`
- **License**: Apache-2.0
- **File**: [`htm.mjs`](htm.mjs)
- **SHA-256**: `79f400b576f899f528a533bfe6d6c14f1ab2af82cedeb6a14a786503e6c79b46`
- **Description**: Hyperscript Tagged Markup. Compiles template literals into Preact JSX virtual nodes in the browser with zero build steps.

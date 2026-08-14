/**
 * HTM 3.1.1 — Hyperscript Tagged Markup
 * https://github.com/developit/htm
 * License: Apache-2.0
 */

const MINI = false;

const CACHE = new Map();

const MODE_SLASH = 0;
const MODE_TEXT = 1;
const MODE_WHITESPACE = 2;
const MODE_TAGNAME = 3;
const MODE_COMMENT = 4;
const MODE_PROP_SET = 5;
const MODE_PROP_APPEND = 6;

const TAG_SET = 1;
const PROPS_SET = 2;
const PROPS_ASSIGN = 3;
const CHILD_RECURSE = 4;
const CHILD_APPEND = 5;

const evaluate = (h, built, fields, args) => {
	let tmp;

	built[0] = 0;

	for (let i = 1; i < built.length; i++) {
		const type = built[i++];

		const value = built[i]
			? ((built[0] |= type ? 1 : 2), fields[built[i++]])
			: built[++i];

		if (type === TAG_SET) {
			args[0] = value;
		} else if (type === PROPS_SET) {
			args[1] = Object.assign(args[1] || {}, value);
		} else if (type === PROPS_ASSIGN) {
			args[1] = args[1] || {};
			args[1][built[++i]] = value;
		} else if (type === CHILD_RECURSE) {
			args.push(h.apply(null, evaluate(h, value, fields, ["", null])));
		} else if (type === CHILD_APPEND) {
			args.push(value);
		}
	}

	return args;
};

export function build(statics) {
	let mode = MODE_TEXT;
	let buffer = '';
	let quote = '';
	let current = [0];
	let char, propName;

	const commit = field => {
		if (mode === MODE_TEXT) {
			if (field || (buffer = buffer.replace(/^\s*\n\s*|\s*\n\s*$/g, ''))) {
				current.push(CHILD_APPEND, field, buffer);
			}
		} else if (mode === MODE_TAGNAME) {
			current.push(TAG_SET, field, buffer);
			mode = MODE_WHITESPACE;
		} else if (mode === MODE_WHITESPACE && buffer === '...' && field) {
			current.push(PROPS_SET, field, 0);
		} else if (mode === MODE_WHITESPACE && buffer && !field) {
			current.push(PROPS_ASSIGN, 0, true, buffer);
		} else if (mode >= MODE_PROP_SET) {
			if (buffer || (!field && mode === MODE_PROP_SET)) {
				current.push(mode, field, buffer, propName);
				mode = MODE_PROP_APPEND;
			}
		}

		buffer = '';
	};

	for (let i = 0; i < statics.length; i++) {
		if (i) {
			if (mode === MODE_TEXT) {
				commit();
			}
			commit(i);
		}

		for (let j = 0; j < statics[i].length; j++) {
			char = statics[i][j];

			if (mode === MODE_TEXT) {
				if (char === '<') {
					commit();
					current = [current];
					mode = MODE_TAGNAME;
				} else {
					buffer += char;
				}
			} else if (mode === MODE_COMMENT) {
				if (buffer === '--' && char === '>') {
					mode = MODE_TEXT;
					buffer = '';
				} else {
					buffer = char + buffer[0];
				}
			} else if (quote) {
				if (char === quote) {
					quote = '';
				} else {
					buffer += char;
				}
			} else if (char === '"' || char === "'") {
				quote = char;
			} else if (char === '>') {
				commit();
				mode = MODE_TEXT;
			} else if (!mode) {
				// MODE_SLASH
			} else if (char === '=') {
				mode = MODE_PROP_SET;
				propName = buffer;
				buffer = '';
			} else if (char === '/') {
				commit();
				if (mode === MODE_TAGNAME) {
					current = current[0];
				}
				mode = current;
				(current = current[0]).push(CHILD_RECURSE, 0, mode);
				mode = MODE_SLASH;
			} else if (char === ' ' || char === '\t' || char === '\n' || char === '\r') {
				commit();
				mode = MODE_WHITESPACE;
			} else {
				buffer += char;
			}

			if (mode === MODE_TAGNAME && buffer === '!--') {
				current = current[0];
				mode = MODE_COMMENT;
			}
		}
	}

	commit();

	return current;
}

export function htm(statics) {
	let fields = [].slice.call(arguments, 1);
	let tree = CACHE.get(statics);
	if (!tree) {
		CACHE.set(statics, (tree = build(statics)));
	}
	return evaluate(this, tree, fields, ["", null]);
}

export default function htmBind(h) {
	return htm.bind(h);
}

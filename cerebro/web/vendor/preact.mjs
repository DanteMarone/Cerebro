/**
 * Preact 10.23.2 + Hooks Standalone Bundle
 * https://preactjs.com
 * License: MIT
 */

let EMPTY_OBJ = {};
let EMPTY_ARR = [];
let IS_NON_DIMENSIONAL = /acit|ex(?:s|g|n|p|$)|rph|grid|ows|mnc|ontw|oip|wra/i;

function assign(obj, props) {
	for (let i in props) obj[i] = props[i];
	return obj;
}

function removeNode(node) {
	let parentNode = node.parentNode;
	if (parentNode) parentNode.removeChild(node);
}

let options = {
	_catchError: function (error, vnode) {
		throw error;
	}
};

export { options };

let vnodeId = 0;

export function createElement(type, props, children) {
	let normalizedProps = {},
		key,
		ref,
		i;
	for (i in props) {
		if (i == 'key') key = props[i];
		else if (i == 'ref') ref = props[i];
		else normalizedProps[i] = props[i];
	}

	if (arguments.length > 2) {
		normalizedProps.children =
			arguments.length > 3 ? EMPTY_ARR.slice.call(arguments, 2) : children;
	}

	if (typeof type == 'function' && type.defaultProps != null) {
		for (i in type.defaultProps) {
			if (normalizedProps[i] === undefined) {
				normalizedProps[i] = type.defaultProps[i];
			}
		}
	}

	return createVNode(type, normalizedProps, key, ref, null);
}

export function createVNode(type, props, key, ref, original) {
	let vnode = {
		type,
		props,
		key,
		ref,
		_children: null,
		_parent: null,
		_depth: 0,
		_dom: null,
		_nextDom: undefined,
		_component: null,
		_hydrated: null,
		constructor: undefined,
		_original: original == null ? ++vnodeId : original
	};

	if (options.vnode != null) options.vnode(vnode);

	return vnode;
}

export const h = createElement;
export const Fragment = function (props) {
	return props.children;
};

// Component & Rendering Core
export function Component(props, context) {
	this.props = props;
	this.context = context;
}

Component.prototype.setState = function (update, callback) {
	let s;
	if (this._nextState != null && this._nextState !== this.state) {
		s = this._nextState;
	} else {
		s = this._nextState = assign({}, this.state);
	}

	if (typeof update == 'function') {
		update = update(assign({}, s), this.props);
	}

	if (update) {
		assign(s, update);
	}

	if (update == null) return;

	if (this._vnode) {
		if (callback) {
			this._renderCallbacks.push(callback);
		}
		enqueueRender(this);
	}
};

Component.prototype.forceUpdate = function (callback) {
	if (this._vnode) {
		this._force = true;
		if (callback) this._renderCallbacks.push(callback);
		enqueueRender(this);
	}
};

Component.prototype.render = Fragment;

let q = [];
let prevDebounce;

function enqueueRender(c) {
	if (
		(!c._dirty &&
			(c._dirty = true) &&
			q.push(c) &&
			!process._rerenderCount++) ||
		prevDebounce !== options.debounceRendering
	) {
		prevDebounce = options.debounceRendering;
		(prevDebounce || setTimeout)(process);
	}
}

function process() {
	let c;
	q.sort((a, b) => a._vnode._depth - b._vnode._depth);
	while ((c = q.shift())) {
		if (c._dirty) {
			let renderCallbacksCounter = c._renderCallbacks.length;
			renderComponent(c);
			while (renderCallbacksCounter--) {
				c._renderCallbacks[renderCallbacksCounter].call(c);
			}
		}
	}
	process._rerenderCount = 0;
}
process._rerenderCount = 0;

function renderComponent(component) {
	let vnode = component._vnode,
		oldDom = vnode._dom,
		parentDom = component._parentDom;

	if (parentDom) {
		let commitQueue = [];
		let oldVNode = assign({}, vnode);
		oldVNode._original = vnode._original + 1;

		diff(
			parentDom,
			vnode,
			oldVNode,
			component._context,
			parentDom.ownerSVGElement !== undefined,
			vnode._hydrated != null ? [oldDom] : null,
			commitQueue,
			oldDom == null ? getDomSibling(oldVNode) : oldDom,
			vnode._hydrated
		);

		commitRoot(commitQueue, vnode);

		if (vnode._dom != oldDom) {
			updateParentDomPointers(vnode);
		}
	}
}

function updateParentDomPointers(vnode) {
	if ((vnode = vnode._parent) != null && vnode._component != null) {
		vnode._dom = vnode._component.base = null;
		for (let i = 0; i < vnode._children.length; i++) {
			let child = vnode._children[i];
			if (child != null && child._dom != null) {
				vnode._dom = vnode._component.base = child._dom;
				break;
			}
		}
		return updateParentDomPointers(vnode);
	}
}

function diff(
	parentDom,
	newVNode,
	oldVNode,
	context,
	isSvg,
	excessDomChildren,
	commitQueue,
	oldDom,
	isHydrating
) {
	let tmp,
		newType = newVNode.type;

	if (newVNode.constructor !== undefined) return null;

	if ((tmp = options._diff)) tmp(newVNode);

	try {
		outer: if (typeof newType == 'function') {
			let c, isNew, oldProps, oldState, snapshot, clearProcessingException;
			let newProps = newVNode.props;

			// Context handling
			tmp = newType.contextType;
			let provider = tmp && context[tmp._id];
			let cctx = tmp
				? provider
					? provider.props.value
					: tmp._defaultValue
				: context;

			if (oldVNode._component) {
				c = newVNode._component = oldVNode._component;
				clearProcessingException = c._processingException = c._pendingError;
			} else {
				if ('prototype' in newType && newType.prototype.render) {
					newVNode._component = c = new newType(newProps, cctx);
				} else {
					newVNode._component = c = new Component(newProps, cctx);
					c.constructor = newType;
					c.render = doRender;
				}
				if (provider) provider.sub(c);

				c.props = newProps;
				if (!c.state) c.state = {};
				c.context = cctx;
				c._context = context;
				isNew = c._dirty = true;
				c._renderCallbacks = [];
			}

			if (c._nextState == null) {
				c._nextState = c.state;
			}

			if (newType.getDerivedStateFromProps != null) {
				if (c._nextState == c.state) {
					c._nextState = assign({}, c._nextState);
				}
				assign(
					c._nextState,
					newType.getDerivedStateFromProps(newProps, c._nextState)
				);
			}

			oldProps = c.props;
			oldState = c.state;

			if (isNew) {
				if (
					newType.getDerivedStateFromProps == null &&
					c.componentWillMount != null
				) {
					c.componentWillMount();
				}
				if (c.componentDidMount != null) {
					c._renderCallbacks.push(c.componentDidMount);
				}
			} else {
				if (
					newType.getDerivedStateFromProps == null &&
					newProps !== oldProps &&
					c.componentWillReceiveProps != null
				) {
					c.componentWillReceiveProps(newProps, cctx);
				}

				if (
					(!c._force &&
						c.shouldComponentUpdate != null &&
						c.shouldComponentUpdate(newProps, c._nextState, cctx) === false) ||
					newVNode._original === oldVNode._original
				) {
					c.props = newProps;
					c.state = c._nextState;
					if (newVNode._original !== oldVNode._original) c._dirty = false;
					c._vnode = newVNode;
					newVNode._dom = oldVNode._dom;
					newVNode._children = oldVNode._children;
					newVNode._children.forEach(vnode => {
						if (vnode) vnode._parent = newVNode;
					});
					if (c._renderCallbacks.length) {
						commitQueue.push(c);
					}
					break outer;
				}

				if (c.componentWillUpdate != null) {
					c.componentWillUpdate(newProps, c._nextState, cctx);
				}

				if (c.componentDidUpdate != null) {
					c._renderCallbacks.push(() => {
						c.componentDidUpdate(oldProps, oldState, snapshot);
					});
				}
			}

			c.context = cctx;
			c.props = newProps;
			c._vnode = newVNode;
			c._parentDom = parentDom;

			let renderHook = options._render,
				count = 0;
			if ('prototype' in newType && newType.prototype.render) {
				c.state = c._nextState;
				c._dirty = false;

				if (renderHook) renderHook(newVNode);

				tmp = c.render(c.props, c.state, c.context);

				for (let k = 0; k < c._renderCallbacks.length; k++) {
					commitQueue.push(c._renderCallbacks[k]);
				}
				c._renderCallbacks = [];
			} else {
				do {
					c._dirty = false;
					if (renderHook) renderHook(newVNode);
					tmp = c.render(c.props, c.state, c.context);
					c.state = c._nextState;
				} while (c._dirty && ++count < 25);
			}

			let isTopLevelFragment =
				tmp != null && tmp.type === Fragment && tmp.key == null;
			let renderResult = isTopLevelFragment ? tmp.props.children : tmp;

			diffChildren(
				parentDom,
				Array.isArray(renderResult) ? renderResult : [renderResult],
				newVNode,
				oldVNode,
				context,
				isSvg,
				excessDomChildren,
				commitQueue,
				oldDom,
				isHydrating
			);

			c.base = newVNode._dom;

			if (options.diffed) options.diffed(newVNode);
		} else if (
			excessDomChildren == null &&
			newVNode._original === oldVNode._original
		) {
			newVNode._children = oldVNode._children;
			newVNode._dom = oldVNode._dom;
		} else {
			newVNode._dom = diffElementNodes(
				oldVNode._dom,
				newVNode,
				oldVNode,
				context,
				isSvg,
				excessDomChildren,
				commitQueue,
				isHydrating
			);
		}

		if ((tmp = options.diffed)) tmp(newVNode);
	} catch (e) {
		newVNode._original = null;
		if (isHydrating || excessDomChildren != null) {
			newVNode._dom = oldDom;
			newVNode._hydrated = true;
			excessDomChildren[excessDomChildren.indexOf(oldDom)] = null;
		}
		options._catchError(e, newVNode, oldVNode);
	}
}

function commitRoot(commitQueue, root) {
	if (options._commit) options._commit(root, commitQueue);

	commitQueue.some(c => {
		try {
			commitQueue = c._renderCallbacks;
			c._renderCallbacks = [];
			commitQueue.forEach(cb => {
				cb.call(c);
			});
		} catch (e) {
			options._catchError(e, c._vnode);
		}
	});
}

function diffElementNodes(
	dom,
	newVNode,
	oldVNode,
	context,
	isSvg,
	excessDomChildren,
	commitQueue,
	isHydrating
) {
	let oldProps = oldVNode.props;
	let newProps = newVNode.props;
	let nodeType = newVNode.type;
	let i;

	if (nodeType === 'svg') isSvg = true;

	if (excessDomChildren != null) {
		for (i = 0; i < excessDomChildren.length; i++) {
			let child = excessDomChildren[i];

			if (
				child &&
				'setAttribute' in child == !!nodeType &&
				(nodeType ? child.localName === nodeType : child.nodeType === 3)
			) {
				dom = child;
				excessDomChildren[i] = null;
				break;
			}
		}
	}

	if (dom == null) {
		if (nodeType === null) {
			return document.createTextNode(newProps);
		}

		if (isSvg) {
			dom = document.createElementNS(
				'http://www.w3.org/2000/svg',
				nodeType
			);
		} else {
			dom = document.createElement(
				nodeType,
				newProps.is && newProps
			);
		}

		excessDomChildren = null;
		isHydrating = false;
	}

	if (nodeType === null) {
		if (oldProps !== newProps && (!isHydrating || dom.data !== newProps)) {
			dom.data = newProps;
		}
	} else {
		excessDomChildren = excessDomChildren && EMPTY_ARR.slice.call(dom.childNodes);
		oldProps = oldVNode.props || EMPTY_OBJ;

		let oldHtml = oldProps.dangerouslySetInnerHTML;
		let newHtml = newProps.dangerouslySetInnerHTML;

		if (!isHydrating) {
			if (excessDomChildren != null) {
				oldProps = {};
				for (i = 0; i < dom.attributes.length; i++) {
					oldProps[dom.attributes[i].name] = dom.attributes[i].value;
				}
			}

			if (newHtml || oldHtml) {
				if (
					!newHtml ||
					((!oldHtml || newHtml.__html !== oldHtml.__html) &&
						newHtml.__html !== dom.innerHTML)
				) {
					dom.innerHTML = (newHtml && newHtml.__html) || '';
				}
			}
		}

		diffProps(dom, newProps, oldProps, isSvg, isHydrating);

		if (newHtml) {
			newVNode._children = [];
		} else {
			i = newVNode.props.children;
			diffChildren(
				dom,
				Array.isArray(i) ? i : [i],
				newVNode,
				oldVNode,
				context,
				isSvg && nodeType !== 'foreignObject',
				excessDomChildren,
				commitQueue,
				excessDomChildren
					? excessDomChildren[0]
					: oldVNode._children && getDomSibling(oldVNode, 0),
				isHydrating
			);

			if (excessDomChildren != null) {
				while ((i = excessDomChildren.pop())) {
					if (i != null) removeNode(i);
				}
			}
		}

		if (!isHydrating) {
			if (
				'value' in newProps &&
				(i = newProps.value) !== undefined &&
				(i !== dom.value ||
					(nodeType === 'progress' && !i) ||
					(nodeType === 'option' && i !== oldProps.value))
			) {
				setProperty(dom, 'value', i, oldProps.value, false);
			}
			if (
				'checked' in newProps &&
				(i = newProps.checked) !== undefined &&
				i !== dom.checked
			) {
				setProperty(dom, 'checked', i, oldProps.checked, false);
			}
		}
	}

	return dom;
}

function diffProps(dom, newProps, oldProps, isSvg, isHydrating) {
	let i;

	for (i in oldProps) {
		if (i !== 'children' && i !== 'key' && !(i in newProps)) {
			setProperty(dom, i, null, oldProps[i], isSvg);
		}
	}

	for (i in newProps) {
		if (
			(!isHydrating || typeof newProps[i] == 'function') &&
			i !== 'children' &&
			i !== 'key' &&
			i !== 'value' &&
			i !== 'checked' &&
			oldProps[i] !== newProps[i]
		) {
			setProperty(dom, i, newProps[i], oldProps[i], isSvg);
		}
	}
}

function setProperty(dom, name, value, oldValue, isSvg) {
	let useCapture;

	o: if (name === 'style') {
		if (typeof value == 'string') {
			dom.style.cssText = value;
		} else {
			if (typeof oldValue == 'string') {
				dom.style.cssText = oldValue = '';
			}

			if (oldValue) {
				for (name in oldValue) {
					if (!(value && name in value)) {
						setStyle(dom.style, name, '');
					}
				}
			}

			if (value) {
				for (name in value) {
					if (!oldValue || value[name] !== oldValue[name]) {
						setStyle(dom.style, name, value[name]);
					}
				}
			}
		}
	} else if (name[0] === 'o' && name[1] === 'n') {
		useCapture =
			name !== (name = name.replace(/Capture$/, ''));

		if (name.toLowerCase() in dom) name = name.toLowerCase().slice(2);
		else name = name.slice(2);

		if (!dom._listeners) dom._listeners = {};
		dom._listeners[name + useCapture] = value;

		if (value) {
			if (!oldValue) {
				let handler = useCapture ? eventProxyCapture : eventProxy;
				dom.addEventListener(name, handler, useCapture);
			}
		} else {
			let handler = useCapture ? eventProxyCapture : eventProxy;
			dom.removeEventListener(name, handler, useCapture);
		}
	} else if (name !== 'dangerouslySetInnerHTML') {
		if (isSvg) {
			name = name.replace(/xlink(H|:h)/, 'h').replace(/sName$/, 's');
		} else if (
			name !== 'width' &&
			name !== 'height' &&
			name !== 'href' &&
			name !== 'list' &&
			name !== 'form' &&
			name !== 'tabIndex' &&
			name !== 'download' &&
			name in dom
		) {
			try {
				dom[name] = value == null ? '' : value;
				break o;
			} catch (e) {}
		}

		if (typeof value === 'function') {
		} else if (
			value != null &&
			(value !== false || (name[0] === 'a' && name[1] === 'r'))
		) {
			dom.setAttribute(name, value);
		} else {
			dom.removeAttribute(name);
		}
	}
}

function eventProxy(e) {
	this._listeners[e.type + false](options.event ? options.event(e) : e);
}

function eventProxyCapture(e) {
	this._listeners[e.type + true](options.event ? options.event(e) : e);
}

function setStyle(style, key, value) {
	if (key[0] === '-') {
		style.setProperty(key, value == null ? '' : value);
	} else if (value == null) {
		style[key] = '';
	} else if (typeof value != 'number' || IS_NON_DIMENSIONAL.test(key)) {
		style[key] = value;
	} else {
		style[key] = value + 'px';
	}
}

function diffChildren(
	parentDom,
	renderResult,
	newParentVNode,
	oldParentVNode,
	context,
	isSvg,
	excessDomChildren,
	commitQueue,
	oldDom,
	isHydrating
) {
	let i, j, oldVNode, childVNode, newDom, firstChildDom, sibDom;

	let oldChildren = (oldParentVNode && oldParentVNode._children) || EMPTY_ARR;
	let oldChildrenLength = oldChildren.length;

	newParentVNode._children = [];
	for (i = 0; i < renderResult.length; i++) {
		childVNode = renderResult[i];

		if (childVNode == null || typeof childVNode == 'boolean') {
			childVNode = newParentVNode._children[i] = null;
		} else if (
			typeof childVNode == 'string' ||
			typeof childVNode == 'number' ||
			typeof childVNode == 'bigint'
		) {
			childVNode = newParentVNode._children[i] = createVNode(
				null,
				childVNode,
				null,
				null,
				childVNode
			);
		} else if (Array.isArray(childVNode)) {
			childVNode = newParentVNode._children[i] = createVNode(
				Fragment,
				{ children: childVNode },
				null,
				null,
				null
			);
		} else if (childVNode._depth > 0) {
			childVNode = newParentVNode._children[i] = createVNode(
				childVNode.type,
				childVNode.props,
				childVNode.key,
				childVNode.ref ? childVNode.ref : null,
				childVNode._original
			);
		} else {
			childVNode = newParentVNode._children[i] = childVNode;
		}

		if (childVNode == null) continue;

		childVNode._parent = newParentVNode;
		childVNode._depth = newParentVNode._depth + 1;

		oldVNode = oldChildren[i];

		if (
			oldVNode === null ||
			(oldVNode &&
				childVNode.key == oldVNode.key &&
				childVNode.type === oldVNode.type)
		) {
			oldChildren[i] = undefined;
		} else {
			for (j = 0; j < oldChildrenLength; j++) {
				oldVNode = oldChildren[j];
				if (
					oldVNode &&
					childVNode.key == oldVNode.key &&
					childVNode.type === oldVNode.type
				) {
					oldChildren[j] = undefined;
					break;
				}
				oldVNode = null;
			}
		}

		oldVNode = oldVNode || EMPTY_OBJ;

		diff(
			parentDom,
			childVNode,
			oldVNode,
			context,
			isSvg,
			excessDomChildren,
			commitQueue,
			oldDom,
			isHydrating
		);

		newDom = childVNode._dom;
		if ((j = childVNode.ref) && oldVNode.ref !== j) {
			if (oldVNode.ref) applyRef(oldVNode.ref, null, childVNode);
			commitQueue.push(() => applyRef(j, childVNode._component || newDom, childVNode));
		}

		if (newDom != null) {
			if (firstChildDom == null) {
				firstChildDom = newDom;
			}

			if (
				typeof childVNode.type == 'function' &&
				childVNode._children === oldVNode._children
			) {
				oldDom = reorderChildren(childVNode, oldDom, parentDom);
			} else {
				oldDom = placeChild(
					parentDom,
					childVNode,
					oldVNode,
					oldChildren,
					newDom,
					oldDom
				);
			}

			if (typeof newParentVNode.type == 'function') {
				newParentVNode._nextDom = oldDom;
			}
		} else if (
			oldDom &&
			oldVNode._dom == oldDom &&
			oldDom.parentNode != parentDom
		) {
			oldDom = getDomSibling(oldVNode);
		}
	}

	newParentVNode._dom = firstChildDom;

	if (excessDomChildren != null && typeof newParentVNode.type != 'function') {
		for (i = excessDomChildren.length; i--; ) {
			if (excessDomChildren[i] != null) removeNode(excessDomChildren[i]);
		}
	}

	for (i = oldChildrenLength; i--; ) {
		if (oldChildren[i] != null) {
			unmount(oldChildren[i], oldChildren[i]);
		}
	}
}

function reorderChildren(childVNode, oldDom, parentDom) {
	for (let a = 0; a < childVNode._children.length; a++) {
		let vnode = childVNode._children[a];
		if (vnode) {
			vnode._parent = childVNode;
			if (typeof vnode.type == 'function') {
				oldDom = reorderChildren(vnode, oldDom, parentDom);
			} else {
				oldDom = placeChild(
					parentDom,
					vnode,
					vnode,
					childVNode._children,
					vnode._dom,
					oldDom
				);
			}
		}
	}
	return oldDom;
}

function placeChild(parentDom, childVNode, oldVNode, oldChildren, newDom, oldDom) {
	let nextDom;
	if (childVNode._nextDom !== undefined) {
		nextDom = childVNode._nextDom;
		childVNode._nextDom = undefined;
	} else if (oldVNode == null || newDom != oldDom || newDom.parentNode == null) {
		outer: if (oldDom == null || oldDom.parentNode !== parentDom) {
			parentDom.appendChild(newDom);
			nextDom = null;
		} else {
			for (let sibDom = oldDom, j = 0; (sibDom = sibDom.nextSibling) && j < oldChildren.length; j += 1) {
				if (sibDom == newDom) {
					break outer;
				}
			}
			parentDom.insertBefore(newDom, oldDom);
			nextDom = oldDom;
		}
	}

	if (nextDom !== undefined) {
		oldDom = nextDom;
	} else {
		oldDom = newDom.nextSibling;
	}
	return oldDom;
}

function unmount(vnode, parentVNode, skipRemove) {
	let r;
	if (options.unmount) options.unmount(vnode);

	if ((r = vnode.ref)) {
		if (!r.current || r.current === vnode._dom) applyRef(r, null, parentVNode);
	}

	if (!skipRemove && typeof vnode.type != 'function') {
		skipRemove = (r = vnode._dom) != null;
	}

	vnode._dom = vnode._nextDom = null;

	if ((r = vnode._component) != null) {
		if (r.componentWillUnmount) {
			try {
				r.componentWillUnmount();
			} catch (e) {
				options._catchError(e, parentVNode);
			}
		}

		r.base = r._parentDom = null;
		vnode._component = null;
	}

	if ((r = vnode._children)) {
		for (let i = 0; i < r.length; i++) {
			if (r[i]) {
				unmount(r[i], parentVNode, skipRemove);
			}
		}
	}

	if (!skipRemove && vnode._dom != null) {
		removeNode(vnode._dom);
	}
}

function doRender(props, state, context) {
	return this.constructor(props, context);
}

export function render(vnode, parentDom) {
	if (options._root) options._root(vnode, parentDom);

	let commitQueue = [];
	let oldVNode = parentDom._children;
	vnode = createVNode(Fragment, { children: [vnode] });
	parentDom._children = vnode;

	diff(
		parentDom,
		vnode,
		oldVNode || EMPTY_OBJ,
		EMPTY_OBJ,
		parentDom.ownerSVGElement !== undefined,
		oldVNode ? null : parentDom.childNodes.length ? EMPTY_ARR.slice.call(parentDom.childNodes) : null,
		commitQueue,
		oldVNode ? oldVNode._dom : parentDom.firstChild,
		false
	);

	commitRoot(commitQueue, vnode);
}

function applyRef(ref, value) {
	if (typeof ref == 'function') ref(value);
	else if (ref) ref.current = value;
}

function getDomSibling(vnode, childIndex) {
	if (childIndex == null) {
		return vnode._parent
			? getDomSibling(vnode._parent, vnode._parent._children.indexOf(vnode) + 1)
			: null;
	}

	let sibling;
	for (; childIndex < vnode._children.length; childIndex++) {
		sibling = vnode._children[childIndex];

		if (sibling != null && sibling._dom != null) {
			return sibling._dom;
		}
	}

	return typeof vnode.type == 'function' ? getDomSibling(vnode) : null;
}

// Preact Hooks
let currentIndex;
let currentComponent;
let currentHook = 0;
let afterPaintEffects = [];
let EMPTY = [];

let oldBeforeDiff = options._diff;
let oldBeforeRender = options._render;
let oldAfterDiff = options.diffed;
let oldCommit = options._commit;
let oldCatchError = options._catchError;
let oldUnmount = options.unmount;

options._diff = vnode => {
	currentComponent = null;
	if (oldBeforeDiff) oldBeforeDiff(vnode);
};

options._render = vnode => {
	if (oldBeforeRender) oldBeforeRender(vnode);

	currentComponent = vnode._component;
	currentIndex = 0;

	let hooks = currentComponent && currentComponent.__hooks;
	if (hooks) {
		hooks._pendingEffects.forEach(invokeCleanup);
		hooks._pendingEffects = [];
		hooks._pendingLayoutEffects.forEach(invokeCleanup);
		hooks._pendingLayoutEffects = [];
	}
};

options.diffed = vnode => {
	if (oldAfterDiff) oldAfterDiff(vnode);

	let c = vnode._component;
	if (c && c.__hooks) {
		let hooks = c.__hooks;
		if (hooks._pendingLayoutEffects.length) {
			hooks._pendingLayoutEffects.forEach(invokeEffect);
			hooks._pendingLayoutEffects = [];
		}
	}
	currentComponent = null;
};

options._commit = (vnode, commitQueue) => {
	commitQueue.some(component => {
		try {
			component._renderCallbacks.forEach(invokeCleanup);
			component._renderCallbacks = [];
		} catch (e) {
			options._catchError(e, component._vnode);
		}
	});

	if (oldCommit) oldCommit(vnode, commitQueue);

	afterPaintEffects.forEach(invokeEffect);
	afterPaintEffects = [];
};

function invokeCleanup(hook) {
	let cleanup = hook._cleanup;
	if (cleanup) {
		hook._cleanup = undefined;
		cleanup();
	}
}

function invokeEffect(hook) {
	let result = hook._value();
	if (typeof result == 'function') {
		hook._cleanup = result;
	}
}

function getHookState(index, type) {
	if (!currentComponent) {
		throw new Error('Hook can only be invoked from render methods.');
	}

	let hooks =
		currentComponent.__hooks ||
		(currentComponent.__hooks = {
			_list: [],
			_pendingEffects: [],
			_pendingLayoutEffects: []
		});

	if (index >= hooks._list.length) {
		hooks._list.push({ _value: undefined });
	}

	return hooks._list[index];
}

export function useState(initialState) {
	currentHook = 1;
	return useReducer(invokeOrReturn, initialState);
}

export function useReducer(reducer, initialState, init) {
	let hookState = getHookState(currentIndex++, 2);
	hookState._reducer = reducer;
	if (!hookState._component) {
		hookState._value = [
			!init ? invokeOrReturn(undefined, initialState) : init(initialState),
			action => {
				let nextValue = hookState._reducer(hookState._value[0], action);
				if (hookState._value[0] !== nextValue) {
					hookState._value[0] = nextValue;
					hookState._component.setState({});
				}
			}
		];

		hookState._component = currentComponent;
	}

	return hookState._value;
}

function invokeOrReturn(arg, f) {
	return typeof f == 'function' ? f(arg) : f;
}

export function useEffect(callback, args) {
	currentHook = 3;
	let state = getHookState(currentIndex++, 3);
	if (argsChanged(state._args, args)) {
		state._value = callback;
		state._args = args;
		currentComponent.__hooks._pendingEffects.push(state);
		afterPaint(currentComponent);
	}
}

export function useRef(initialValue) {
	currentHook = 5;
	return useMemo(() => ({ current: initialValue }), []);
}

export function useMemo(factory, args) {
	currentHook = 7;
	let state = getHookState(currentIndex++, 7);
	if (argsChanged(state._args, args)) {
		state._value = factory();
		state._args = args;
		state._factory = factory;
	}
	return state._value;
}

export function useCallback(callback, args) {
	currentHook = 8;
	return useMemo(() => callback, args);
}

function argsChanged(oldArgs, newArgs) {
	return (
		!oldArgs ||
		oldArgs.length !== newArgs.length ||
		newArgs.some((arg, index) => arg !== oldArgs[index])
	);
}

function afterPaint(component) {
	if (afterPaintEffects.length === 0) {
		requestAnimationFrame(() => {
			setTimeout(() => {
				afterPaintEffects.forEach(invokeEffect);
				afterPaintEffects = [];
			}, 0);
		});
	}
}

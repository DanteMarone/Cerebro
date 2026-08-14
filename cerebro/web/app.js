/**
 * Cerebro v2 Front-End Application
 * Built with pure Preact Hyperscript (Zero-build, zero parser overhead, 100% reliable)
 */

// Resolved by the import map in index.html to the verified upstream artifacts in vendor/.
// Do not point these at a hand-written bundle: see vendor/VENDOR.md.
import { h, render } from "preact";
import { useState, useEffect, useRef, useCallback } from "preact/hooks";

function App() {
    const [channels, setChannels] = useState([]);
    const [agents, setAgents] = useState([]);
    const [activeChannelId, setActiveChannelId] = useState("dm-dante-jarvis");
    const [messages, setMessages] = useState({});
    const [streamingDeltas, setStreamingDeltas] = useState({});
    const [thinkingDeltas, setThinkingDeltas] = useState({});
    const [drafts, setDrafts] = useState({});
    const [connected, setConnected] = useState(false);
    const [sending, setSending] = useState(false);
    const [isPinned, setIsPinned] = useState(true);

    const streamRef = useRef(null);
    const wsRef = useRef(null);
    const reconnectTimerRef = useRef(null);

    const currentDraft = drafts[activeChannelId] || "";

    // Fetch initial channels and agents
    useEffect(() => {
        async function loadInitialData() {
            try {
                const [channelsRes, agentsRes] = await Promise.all([
                    fetch("/api/channels"),
                    fetch("/api/agents")
                ]);
                if (channelsRes.ok && agentsRes.ok) {
                    const channelsData = await channelsRes.json();
                    const agentsData = await agentsRes.json();
                    setChannels(channelsData.channels || []);
                    setAgents(agentsData.agents || []);
                    if (channelsData.channels?.length > 0) {
                        const hasDm = channelsData.channels.some(c => c.id === "dm-dante-jarvis");
                        if (!hasDm) {
                            setActiveChannelId(channelsData.channels[0].id);
                        }
                    }
                }
            } catch (err) {
                console.error("Failed to load initial data:", err);
            }
        }
        loadInitialData();
    }, []);

    // Load message history when active channel changes
    const loadChannelMessages = useCallback(async (channelId, afterId = null) => {
        if (!channelId) return;
        try {
            const url = afterId 
                ? `/api/channels/${channelId}/messages?after=${afterId}`
                : `/api/channels/${channelId}/messages?limit=200`;
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                setMessages(prev => {
                    const existing = prev[channelId] || [];
                    if (afterId) {
                        const existingIds = new Set(existing.map(m => m.id));
                        const brandNew = (data.messages || []).filter(m => !existingIds.has(m.id));
                        return { ...prev, [channelId]: [...existing, ...brandNew] };
                    } else {
                        return { ...prev, [channelId]: data.messages || [] };
                    }
                });
            }
        } catch (err) {
            console.error(`Failed to load messages for ${channelId}:`, err);
        }
    }, []);

    useEffect(() => {
        loadChannelMessages(activeChannelId);
        setIsPinned(true);
        if (streamRef.current) {
            setTimeout(() => {
                if (streamRef.current) {
                    streamRef.current.scrollTop = streamRef.current.scrollHeight;
                }
            }, 50);
        }
    }, [activeChannelId, loadChannelMessages]);

    // WebSocket connection and event handling
    useEffect(() => {
        let isCancelled = false;

        function connectWs() {
            if (isCancelled) return;
            const protocol = location.protocol === "https:" ? "wss:" : "ws:";
            const wsUrl = `${protocol}//${location.host}/ws`;
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;

            ws.onopen = () => {
                if (isCancelled) return;
                setConnected(true);
                setMessages(prev => {
                    const currentList = prev[activeChannelId] || [];
                    const lastId = currentList.length > 0 ? currentList[currentList.length - 1].id : null;
                    if (lastId) {
                        loadChannelMessages(activeChannelId, lastId);
                    }
                    return prev;
                });
            };

            ws.onmessage = (event) => {
                try {
                    const envelope = JSON.parse(event.data);
                    const type = envelope.type;
                    const payload = envelope.payload || {};

                    if (type === "message.new") {
                        const msg = payload.message;
                        const channelId = payload.channel_id;
                        if (msg && channelId) {
                            setMessages(prev => {
                                const list = prev[channelId] || [];
                                if (list.some(m => m.id === msg.id)) return prev;
                                return { ...prev, [channelId]: [...list, msg] };
                            });
                        }
                    } else if (type === "agent.thinking") {
                        const { message_id, text } = payload;
                        if (message_id != null && text) {
                            setThinkingDeltas(prev => ({
                                ...prev,
                                [message_id]: (prev[message_id] || "") + text
                            }));
                        }
                    } else if (type === "message.delta") {
                        const { message_id, text } = payload;
                        if (message_id != null && text) {
                            setStreamingDeltas(prev => ({
                                ...prev,
                                [message_id]: (prev[message_id] || "") + text
                            }));
                        }
                    } else if (type === "message.done") {
                        // The runtime publishes {channel_id, message}, the same envelope as
                        // message.new. Reading payload.id here left the guard below always false,
                        // so the handler never ran: the thinking block never cleared and the live
                        // stream was never replaced by the authoritative persisted row.
                        const msg = payload.message;
                        if (msg && msg.id != null) {
                            const channelId = msg.channel_id;
                            setStreamingDeltas(prev => {
                                const next = { ...prev };
                                delete next[msg.id];
                                return next;
                            });
                            setThinkingDeltas(prev => {
                                const next = { ...prev };
                                delete next[msg.id];
                                return next;
                            });
                            if (channelId) {
                                setMessages(prev => {
                                    const list = prev[channelId] || [];
                                    const idx = list.findIndex(m => m.id === msg.id);
                                    if (idx >= 0) {
                                        const updated = [...list];
                                        updated[idx] = msg;
                                        return { ...prev, [channelId]: updated };
                                    } else {
                                        return { ...prev, [channelId]: [...list, msg] };
                                    }
                                });
                            }
                        }
                    }
                } catch (err) {
                    console.debug("Failed to parse WS message:", err);
                }
            };

            ws.onclose = () => {
                if (isCancelled) return;
                setConnected(false);
                reconnectTimerRef.current = setTimeout(connectWs, 2000);
            };

            ws.onerror = () => {
                ws.close();
            };
        }

        connectWs();

        return () => {
            isCancelled = true;
            if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
            if (wsRef.current) wsRef.current.close();
        };
    }, [activeChannelId, loadChannelMessages]);

    const handleScroll = () => {
        if (!streamRef.current) return;
        const { scrollTop, scrollHeight, clientHeight } = streamRef.current;
        const pinned = scrollHeight - scrollTop - clientHeight < 60;
        setIsPinned(pinned);
    };

    useEffect(() => {
        if (isPinned && streamRef.current) {
            streamRef.current.scrollTop = streamRef.current.scrollHeight;
        }
    }, [messages, streamingDeltas, thinkingDeltas, isPinned]);

    const handleSendMessage = async () => {
        const text = currentDraft.trim();
        if (!text || sending || !activeChannelId) return;

        setSending(true);
        try {
            const res = await fetch(`/api/channels/${activeChannelId}/messages`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    content: text,
                    author_id: "dante",
                    type: "chat"
                })
            });

            if (res.ok) {
                setDrafts(prev => ({ ...prev, [activeChannelId]: "" }));
                const newMsg = await res.json();
                setMessages(prev => {
                    const list = prev[activeChannelId] || [];
                    if (list.some(m => m.id === newMsg.id)) return prev;
                    return { ...prev, [activeChannelId]: [...list, newMsg] };
                });
                setIsPinned(true);
            }
        } catch (err) {
            console.error("Failed to send message:", err);
        } finally {
            setSending(false);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    };

    const activeChannel = channels.find(c => c.id === activeChannelId) || {
        id: activeChannelId,
        name: activeChannelId,
        topic: ""
    };

    const currentMessages = messages[activeChannelId] || [];

    return h("div", { id: "app" }, [
        // Sidebar
        h("aside", { class: "sidebar" }, [
            h("div", { class: "sidebar-header" }, [
                h("h1", null, "⚡ Cerebro"),
                h("div", { class: "status-badge" }, [
                    h("span", { class: `status-dot ${connected ? 'online' : ''}` }),
                    h("span", null, connected ? 'live' : 'offline'),
                ]),
            ]),
            h("div", { class: "sidebar-content" }, [
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-title" }, "Direct Messages"),
                    ...channels.filter(c => c.type === 'dm' || c.kind === 'dm').map(ch =>
                        h("div", {
                            key: ch.id,
                            class: `nav-item ${ch.id === activeChannelId ? 'active' : ''}`,
                            onClick: () => setActiveChannelId(ch.id)
                        }, [
                            h("span", { class: "nav-icon" }, "👤"),
                            h("span", null, ch.name)
                        ])
                    )
                ]),
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-title" }, "Channels"),
                    ...channels.filter(c => c.type !== 'dm' && c.kind !== 'dm').map(ch =>
                        h("div", {
                            key: ch.id,
                            class: `nav-item ${ch.id === activeChannelId ? 'active' : ''}`,
                            onClick: () => setActiveChannelId(ch.id)
                        }, [
                            h("span", { class: "nav-icon" }, "#"),
                            h("span", null, ch.name)
                        ])
                    )
                ]),
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-title" }, `Agents (${agents.length})`),
                    ...agents.map(ag =>
                        h("div", { key: ag.id, class: "nav-item", style: "cursor: default; opacity: 0.9;" }, [
                            h("span", { class: "nav-icon" }, ag.avatar || "🤖"),
                            h("span", null, ag.display_name || ag.name)
                        ])
                    )
                ])
            ])
        ]),

        // Main Chat
        h("main", { class: "chat-container", style: "position: relative;" }, [
            h("header", { class: "chat-header" }, [
                h("div", { class: "chat-header-title" }, [
                    h("span", null, (activeChannel.type === 'dm' || activeChannel.kind === 'dm') ? `👤 @${activeChannel.name}` : `#${activeChannel.name}`),
                    activeChannel.topic ? h("span", { class: "chat-header-topic" }, `— ${activeChannel.topic}`) : null
                ])
            ]),

            // Message Stream
            h("div", { class: "message-stream", ref: streamRef, onScroll: handleScroll }, [
                currentMessages.length === 0 ? h("div", { style: "text-align: center; color: var(--text-secondary); margin-top: 3rem;" }, [
                    h("p", { style: "font-size: 1.1rem; font-weight: 500;" }, `Welcome to #${activeChannel.name}`),
                    h("p", { style: "font-size: 0.85rem; margin-top: 0.3rem;" }, "Start the conversation below.")
                ]) : null,

                ...currentMessages.map(msg => {
                    const displayAuthorId = msg.display_author_id || msg.author_id;
                    const isUser = displayAuthorId === 'dante';
                    const delta = streamingDeltas[msg.id];
                    const thinking = thinkingDeltas[msg.id];
                    const base = msg.body ?? msg.content ?? '';
                    const content = delta ? (base + delta) : base;
                    const timeStr = msg.created_at ? msg.created_at.slice(11, 16) : '';

                    return h("div", { key: msg.id, class: "message-row" }, [
                        h("div", { class: `message-avatar ${isUser ? 'user' : ''}` },
                            isUser ? 'D' : (displayAuthorId?.[0]?.toUpperCase() || 'J')
                        ),
                        h("div", { class: "message-body" }, [
                            h("div", { class: "message-meta" }, [
                                h("span", { class: "message-author" },
                                    isUser ? 'Dante' : displayAuthorId
                                ),
                                h("span", { class: "message-time" }, timeStr)
                            ]),
                            thinking ? h("div", { class: "thinking-block" }, [
                                h("div", { class: "thinking-header" }, "💭 Thinking..."),
                                h("div", { class: "thinking-content" }, thinking)
                            ]) : null,
                            h("div", { class: "message-content" }, [
                                content,
                                delta ? h("span", { class: "streaming-cursor" }) : null
                            ])
                        ])
                    ]);
                })
            ]),

            // Jump to latest button
            !isPinned ? h("button", {
                class: "jump-bottom-btn",
                onClick: () => {
                    if (streamRef.current) {
                        streamRef.current.scrollTop = streamRef.current.scrollHeight;
                        setIsPinned(true);
                    }
                }
            }, "↓ Jump to latest") : null,

            // Composer
            h("div", { class: "composer-container" }, [
                h("div", { class: "composer-box" }, [
                    h("textarea", {
                        class: "composer-textarea",
                        placeholder: `Message ${(activeChannel.type === 'dm' || activeChannel.kind === 'dm') ? '@' : '#'}${activeChannel.name}…`,
                        value: currentDraft,
                        onInput: (e) => setDrafts(prev => ({ ...prev, [activeChannelId]: e.target.value })),
                        onKeyDown: handleKeyDown,
                        disabled: sending,
                        autofocus: true
                    }),
                    h("div", { class: "composer-footer" }, [
                        h("span", null, [
                            h("strong", null, "Enter"),
                            " to send, ",
                            h("strong", null, "Shift + Enter"),
                            " for new line"
                        ]),
                        h("button", {
                            class: "send-button",
                            onClick: handleSendMessage,
                            disabled: !currentDraft.trim() || sending
                        }, "Send")
                    ])
                ])
            ])
        ])
    ]);
}

const mountTarget = document.getElementById("app") || document.body;
render(h(App, null), mountTarget);

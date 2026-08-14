/**
 * Cerebro v2 Front-End Application
 * Built with pure Preact Hyperscript (Zero-build, zero parser overhead, 100% reliable)
 */

import { h, render } from "./vendor/preact.module.js";
import { useState, useEffect, useRef, useCallback } from "./vendor/hooks.module.js";

function App() {
    const [channels, setChannels] = useState([]);
    const [agents, setAgents] = useState([]);
    const [activeChannelId, setActiveChannelId] = useState("warroom");
    const [channelMembers, setChannelMembers] = useState([]);
    const [messages, setMessages] = useState({});
    const [streamingDeltas, setStreamingDeltas] = useState({});
    const [thinkingDeltas, setThinkingDeltas] = useState({});
    const [drafts, setDrafts] = useState({});
    const [connected, setConnected] = useState(false);
    const [sending, setSending] = useState(false);
    const [isPinned, setIsPinned] = useState(true);

    // Modal state for channel creation
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [newChanName, setNewChanName] = useState("");
    const [newChanTopic, setNewChanTopic] = useState("");
    const [selectedAgents, setSelectedAgents] = useState([]);
    const [creatingChannel, setCreatingChannel] = useState(false);

    const streamRef = useRef(null);
    const wsRef = useRef(null);
    const reconnectTimerRef = useRef(null);

    const currentDraft = drafts[activeChannelId] || "";

    // Fetch initial channels and agents
    const loadChannelsAndAgents = useCallback(async () => {
        try {
            const [channelsRes, agentsRes] = await Promise.all([
                fetch("/api/channels"),
                fetch("/api/agents")
            ]);
            if (channelsRes.ok && agentsRes.ok) {
                const channelsData = await channelsRes.json();
                const agentsData = await agentsRes.json();
                const chList = channelsData.channels || [];
                setChannels(chList);
                setAgents(agentsData.agents || []);
                if (chList.length > 0 && !chList.some(c => c.id === activeChannelId)) {
                    const warRoom = chList.find(c => c.id === "warroom");
                    setActiveChannelId(warRoom ? "warroom" : chList[0].id);
                }
            }
        } catch (err) {
            console.error("Failed to load initial data:", err);
        }
    }, [activeChannelId]);

    useEffect(() => {
        loadChannelsAndAgents();
    }, [loadChannelsAndAgents]);

    // Fetch members for the active channel
    const loadActiveMembers = useCallback(async (channelId) => {
        if (!channelId) return;
        try {
            const res = await fetch(`/api/channels/${channelId}/members`);
            if (res.ok) {
                const data = await res.json();
                setChannelMembers(data.members || []);
            }
        } catch (err) {
            console.error(`Failed to load members for ${channelId}:`, err);
        }
    }, []);

    // Load message history when active channel changes
    const loadChannelMessages = useCallback(async (channelId, afterId = null) => {
        if (!channelId) return;
        try {
            const url = afterId 
                ? `/api/channels/${channelId}/messages?after=${afterId}`
                : `/api/channels/${channelId}/messages`;
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
        loadActiveMembers(activeChannelId);
        setIsPinned(true);
        if (streamRef.current) {
            setTimeout(() => {
                if (streamRef.current) {
                    streamRef.current.scrollTop = streamRef.current.scrollHeight;
                }
            }, 50);
        }
    }, [activeChannelId, loadChannelMessages, loadActiveMembers]);

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
                        const msg = payload.message || payload;
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
                    } else if (type === "channel.new" || type === "channel.update") {
                        // A channel created while the page is open -- by Dante in another tab, or
                        // by an agent opening a room (§6.4) -- was previously invisible until F5,
                        // because the sidebar was only ever populated once on mount.
                        loadChannelsAndAgents();
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
    }, [activeChannelId, loadChannelMessages, loadChannelsAndAgents]);

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

    const handleCreateChannel = async (e) => {
        e.preventDefault();
        const name = newChanName.trim();
        if (!name || creatingChannel) return;

        setCreatingChannel(true);
        try {
            const res = await fetch("/api/channels", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: name,
                    topic: newChanTopic.trim(),
                    member_ids: selectedAgents,
                    kind: "topic"
                })
            });

            if (res.ok) {
                const data = await res.json();
                const created = data.channel;
                await loadChannelsAndAgents();
                setShowCreateModal(false);
                setNewChanName("");
                setNewChanTopic("");
                setSelectedAgents([]);
                if (created && created.id) {
                    setActiveChannelId(created.id);
                }
            } else {
                const err = await res.json();
                alert(err.detail || "Failed to create channel");
            }
        } catch (err) {
            console.error("Channel creation error:", err);
            alert("Error creating channel");
        } finally {
            setCreatingChannel(false);
        }
    };

    const toggleAgentSelection = (agentId) => {
        setSelectedAgents(prev => 
            prev.includes(agentId) ? prev.filter(id => id !== agentId) : [...prev, agentId]
        );
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
                // Direct Messages
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-header" }, [
                        h("span", null, "Direct Messages")
                    ]),
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

                // Channels (with + button)
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-header" }, [
                        h("span", null, "Channels"),
                        h("button", {
                            class: "section-add-btn",
                            title: "Create Channel",
                            onClick: () => setShowCreateModal(true)
                        }, "+")
                    ]),
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

                // Agent Roster
                h("div", { class: "sidebar-section" }, [
                    h("div", { class: "sidebar-section-header" }, [
                        h("span", null, `Agents (${agents.length})`)
                    ]),
                    ...agents.map(ag =>
                        h("div", { key: ag.id, class: "nav-item", style: "cursor: default; opacity: 0.9;" }, [
                            h("span", { class: "nav-icon" }, ag.avatar || "🤖"),
                            h("span", null, ag.display_name || ag.name)
                        ])
                    )
                ])
            ])
        ]),

        // Main Chat Area
        h("main", { class: "chat-container", style: "position: relative;" }, [
            h("header", { class: "chat-header" }, [
                h("div", { class: "chat-header-title" }, [
                    h("span", null, (activeChannel.type === 'dm' || activeChannel.kind === 'dm') ? `👤 @${activeChannel.name}` : `#${activeChannel.name}`),
                    activeChannel.topic ? h("span", { class: "chat-header-topic" }, `— ${activeChannel.topic}`) : null
                ]),
                h("div", { class: "chat-header-actions" }, [
                    channelMembers.length > 0 ? h("div", { class: "member-pill" }, [
                        h("span", null, `👥 ${channelMembers.length} members`)
                    ]) : null
                ])
            ]),

            // Message Stream
            h("div", { class: "message-stream", ref: streamRef, onScroll: handleScroll }, [
                currentMessages.length === 0 ? h("div", { style: "text-align: center; color: var(--text-secondary); margin-top: 3rem;" }, [
                    h("p", { style: "font-size: 1.1rem; font-weight: 500;" }, `Welcome to #${activeChannel.name}`),
                    h("p", { style: "font-size: 0.85rem; margin-top: 0.3rem;" }, "Start the conversation below.")
                ]) : null,

                ...currentMessages.map(msg => {
                    const author = msg.display_author_id || msg.author_id;
                    const isUser = author === 'dante';
                    const delta = streamingDeltas[msg.id];
                    const thinking = thinkingDeltas[msg.id];
                    const base = msg.body ?? msg.content ?? '';
                    const content = delta ? (base + delta) : base;
                    const timeStr = msg.created_at ? msg.created_at.slice(11, 16) : '';

                    return h("div", { key: msg.id, class: "message-row" }, [
                        h("div", { class: `message-avatar ${isUser ? 'user' : ''}` },
                            isUser ? 'D' : (author?.[0]?.toUpperCase() || 'J')
                        ),
                        h("div", { class: "message-body" }, [
                            h("div", { class: "message-meta" }, [
                                h("span", { class: "message-author" }, isUser ? 'Dante' : author),
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
        ]),

        // Create Channel Modal Dialog
        showCreateModal ? h("div", { class: "modal-backdrop", onClick: (e) => {
            if (e.target === e.currentTarget) setShowCreateModal(false);
        }}, [
            h("div", { class: "modal-dialog" }, [
                h("div", { class: "modal-header" }, [
                    h("h2", null, "Create Channel"),
                    h("button", { class: "modal-close-btn", onClick: () => setShowCreateModal(false) }, "✕")
                ]),
                h("div", { class: "modal-body" }, [
                    h("div", { class: "form-group" }, [
                        h("label", { class: "form-label" }, "Channel Name"),
                        h("input", {
                            class: "form-input",
                            type: "text",
                            placeholder: "e.g. general, feature-planning",
                            value: newChanName,
                            onInput: (e) => setNewChanName(e.target.value),
                            autofocus: true
                        })
                    ]),
                    h("div", { class: "form-group" }, [
                        h("label", { class: "form-label" }, "Topic (Optional)"),
                        h("input", {
                            class: "form-input",
                            type: "text",
                            placeholder: "What is this channel about?",
                            value: newChanTopic,
                            onInput: (e) => setNewChanTopic(e.target.value)
                        })
                    ]),
                    h("div", { class: "form-group" }, [
                        h("label", { class: "form-label" }, "Add Agents to Channel"),
                        h("div", { class: "agent-checkbox-grid" }, [
                            ...agents.map(ag => h("label", { key: ag.id, class: "agent-checkbox-item" }, [
                                h("input", {
                                    type: "checkbox",
                                    checked: selectedAgents.includes(ag.id),
                                    onChange: () => toggleAgentSelection(ag.id)
                                }),
                                h("span", null, `${ag.avatar || '🤖'} ${ag.name}`)
                            ]))
                        ])
                    ]),
                    h("p", { style: "font-size: 0.78rem; color: var(--text-secondary); margin-top: 0.2rem;" },
                        "🔒 You (@dante) are automatically enrolled as the channel owner."
                    )
                ]),
                h("div", { class: "modal-footer" }, [
                    h("button", { class: "btn-secondary", onClick: () => setShowCreateModal(false) }, "Cancel"),
                    h("button", {
                        class: "btn-primary",
                        disabled: !newChanName.trim() || creatingChannel,
                        onClick: handleCreateChannel
                    }, creatingChannel ? "Creating..." : "Create Channel")
                ])
            ])
        ]) : null
    ]);
}

const mountTarget = document.getElementById("app") || document.body;
render(h(App, null), mountTarget);

// game.js — 游戏状态、动作执行、事件绑定、初始化
// 棋盘函数见 game-board.js，战斗弹窗见 game-combat.js
// 所有共享状态通过 window.SMW 命名空间暴露

(function() {
    const S = window.SMW = window.SMW || {};

    // --- 1. 状态初始化 ---

    const gameDataElement = document.getElementById('game-data');
    const data = JSON.parse(gameDataElement.textContent);

    // 共享状态变量
    S.selectedAction = {};
    S.diceModalTimer = null;
    S.clashModalTimer = null;

    function updateCellSize() {
        const style = getComputedStyle(document.documentElement);
        const raw = style.getPropertyValue('--cell-size').trim();
        if (raw.startsWith('calc')) {
            const w = window.innerWidth;
            const gutter = 8;
            const rawSize = Math.floor((w - gutter) / 10);
            S.CELL_SIZE_PX = Math.max(30, Math.min(50, rawSize));
        } else {
            const parsed = parseFloat(raw);
            S.CELL_SIZE_PX = isNaN(parsed) ? 50 : parsed;
        }
        document.documentElement.style.setProperty('--cell-size', S.CELL_SIZE_PX + 'px');
    }
    updateCellSize();

    // 从 data 对象解构所有动态数据
    S.allEntities = data.allEntities;
    S.playerID = data.playerID;
    S.playerEntity = data.playerEntity;
    S.aiEntity = data.aiEntity;
    S.orientationMap = data.orientationMap;
    S.apiUrls = data.apiUrls;
    S.playerLoadout = data.playerLoadout;
    S.aiOpponentName = data.aiOpponentName;

    S.gameState = {
        turnPhase: S.playerEntity ? S.playerEntity.turn_phase : 'timing',
        timing: S.playerEntity ? S.playerEntity.timing : null,
        openingMoveTaken: S.playerEntity ? S.playerEntity.opening_move_taken : false,
        isPlayerLocked: data.isPlayerLocked,
        gameOver: data.gameOver,
        pendingEffect: S.playerEntity && S.playerEntity.pending_combat && S.playerEntity.pending_combat.stage && S.playerEntity.pending_combat.stage.includes('EFFECT') ? true : false,
        pendingReroll: S.playerEntity && S.playerEntity.pending_combat && S.playerEntity.pending_combat.stage && S.playerEntity.pending_combat.stage.includes('REROLL') ? true : false,
        visualEvents: data.visualEvents,
        runProjectilePhase: data.runProjectilePhase,
        gameMode: data.gameMode,
        defeatCount: data.defeatCount
    };

    // 静态常量
    S.effectDescriptions = {
        'devastating': { title: '【毁伤】', text: '对目标结构造成二次伤害', style: 'background-color: var(--status-damaged);' },
        'scattershot': { title: '【霰射】', text: '对随机部件造成溢出伤害', style: 'background-color: var(--status-destroyed);' },
        'cleave': { title: '【顺劈】', text: '对随机部件造成溢出伤害', style: 'background-color: #805ad5;' }
    };
    S.diceIconMap = {
        '重击': 'H', '轻击': 'L', '防御': 'D', '闪避': 'E',
        '空心重击': 'h', '空心轻击': 'l', '空心防御': 'd',
        '闪电': '⚡', '眼睛': '👁', '空白': ' '
    };
    S.diceColorMap = {
        'yellow_count': 'yellow', 'red_count': 'red', 'white_count': 'white', 'blue_count': 'blue'
    };

    // DOM 缓存
    let partDetailModalBackdrop, partDetailTitle, partDetailImage, partDetailStatsContainer, partDetailStatsList, partDetailActionsList;
    // --- 2. 动作执行与事件处理 ---

    function showErrorModal(title, message) {
        const backdrop = document.getElementById('error-modal-backdrop');
        const titleEl = document.getElementById('error-title');
        const messageEl = document.getElementById('error-message');

        if (backdrop && titleEl && messageEl) {
            titleEl.innerText = title || '发生未知错误';
            messageEl.innerText = message || '请检查控制台并刷新页面。';
            backdrop.style.display = 'flex';
        } else {
            console.error("CRITICAL: Error modal HTML elements not found.");
            alert(`发生严重错误:\nTitle: ${title}\nMessage: ${message}\n自动重载已停止。`);
        }
        document.querySelectorAll('.action-item, .btn, .selector-group button').forEach(el => {
            if (!el.closest('#error-modal')) {
                el.disabled = true;
            }
        });
    }

    function showGameOverModal(status) {
        if (window.recordGameOutcome) {
            window.recordGameOutcome(status, S.playerLoadout, S.aiOpponentName);
        }

        let modal;
        if (status === 'ai_defeated_in_range') {
            modal = document.getElementById('range-continue-modal');
        } else {
            modal = document.getElementById('game-over-modal');
            const title = document.getElementById('game-over-title');
            if (status === 'player_win') {
                title.innerText = '胜利！';
                title.style.color = 'var(--status-ok)';
            } else {
                title.innerText = '失败！';
                if (S.gameState.gameMode === 'horde') { title.innerText = `结束\n最终击败数: ${S.gameState.defeatCount}`; }
                title.style.color = 'var(--status-destroyed)';
            }
        }
        if (modal) { modal.style.display = 'block'; }
        document.querySelectorAll('.action-item, .btn, .selector-group button').forEach(el => {
            if (!el.closest('#game-over-modal') && !el.closest('#range-continue-modal')) {
                el.disabled = true;
            }
        });
    }

    function selectAction(name, range, type, cost, partSlot) {
        if (S.gameState.pendingEffect || S.gameState.pendingReroll) return;
        S.clearHighlights();
        S.selectedAction = { name, range, type, cost, slot: partSlot, player_id: S.playerID };

        let url = '', body = { action_name: name, part_slot: partSlot, player_id: S.playerID };

        if (type === '移动' || name === '调整移动') {
            url = S.apiUrls.getMoveRange;
        } else if (type === '近战' || type === '射击' || type === '抛射' || type === '快速') {
            url = S.apiUrls.getAttackRange;
        } else if (name === '仅转向') {
            S.showOrientationSelector(S.playerEntity.pos[0], S.playerEntity.pos[1], true);
            return;
        }

        if(url) {
            fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })
            .then(res => res.json())
            .then(data => {
                if(data.valid_moves) data.valid_moves.forEach(([x,y]) => {
                    const c = document.getElementById(`cell-${x}-${y}`);
                    if (c) {
                        c.classList.add('highlight-move');
                        c.onclick = () => S.showOrientationSelector(x,y);
                    }
                });
                if(data.valid_targets) data.valid_targets.forEach(t => {
                    const [x,y] = t.pos;
                    const c = document.getElementById(`cell-${x}-${y}`);
                    if (c) {
                        c.classList.add('highlight-attack');
                        c.onclick = () => initiateAttack(t.entity_id, x, y, t.is_back_attack);
                    }
                });
                if(data.valid_launch_cells) data.valid_launch_cells.forEach(([x,y]) => {
                    const c = document.getElementById(`cell-${x}-${y}`);
                    if (c) {
                        c.classList.add('highlight-launch');
                        if (!c.classList.contains('highlight-attack')) {
                            c.onclick = () => initiateLaunch(x, y);
                        }
                    }
                });
            });
        }
    }

    function initiateJettison(partSlot) {
        if (S.gameState.pendingEffect || S.gameState.pendingReroll) return;
        S.clearHighlights();
        postAndReload(S.apiUrls.jettisonPart, {
            action_name: '【弃置】',
            part_slot: partSlot
        });
    }

    function initiateAttack(entityId, x, y, isBackAttack) {
        S.selectedAction.targetEntityId = entityId;
        S.selectedAction.targetPos = [x, y];
        executeAttack();
    }

    function initiateLaunch(x, y) {
        S.selectedAction.targetEntityId = null;
        S.selectedAction.targetPos = [x, y];
        executeAttack();
    }

    function confirmPartSelection(partSlot) {
        S.selectedAction.targetPartName = partSlot;
        S.closePartSelector();
        executeAttack();
    }

    function postAndReload(url, body = {}) {
        if (window.__actionInFlight) {
            console.warn("Action already in flight, ignoring duplicate request:", url);
            return;
        }
        window.__actionInFlight = true;

        body.player_id = S.playerID;
        console.log("Calling postAndReload for:", url, body);

        fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })
        .then(async res => {
            if (res.redirected) {
                console.log("Response was a redirect, reloading...");
                window.location.href = res.url;
                return null;
            }
            if (!res.ok) {
                let errorMsg = `HTTP 错误! 状态: ${res.status} ${res.statusText}`;
                try {
                    const errData = await res.json();
                    if (errData && errData.message) {
                        errorMsg = errData.message;
                    }
                } catch (e) {}
                throw new Error(errorMsg);
            }
            return res.json();
        })
        .then(data => {
            if (!data) return;

            console.log("Received data:", data);

            if(data.success) {
                if (data.action_required === 'select_part') {
                    console.log("Action required: select_part. Showing modal.");
                    window.__actionInFlight = false;
                    S.showPartSelector();
                    return;
                }

                if (data.action_required === 'select_reroll') {
                    console.log("Action required: select_reroll. Showing modal.");
                    window.__actionInFlight = false;
                    const rerollData = data;
                    const attackerIsPlayer = (rerollData.attacker_name.includes("玩家"));
                    const defenderIsPlayer = (rerollData.defender_name.includes("玩家"));
                    S.showDiceRollModal(
                        rerollData.dice_details,
                        rerollData.action_name,
                        rerollData.attacker_name,
                        rerollData.defender_name,
                        true,
                        attackerIsPlayer,
                        defenderIsPlayer
                    );
                    return;
                }

                if (data.action_required === 'select_effect') {
                    console.log("Action required: select_effect. Showing modal.");
                    window.__actionInFlight = false;
                    S.showEffectSelector(data.options);
                    return;
                }

                // 可能需要运行抛射物阶段（AI 回合延续等场景）
                if (data.run_projectile_phase) {
                    console.log("run_projectile_phase triggered from action response, processing...");
                    setTimeout(function() {
                        fetch(S.apiUrls.runProjectilePhase, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({player_id: S.playerID})
                        })
                        .then(function(res) { return res.json(); })
                        .then(function(pdata) {
                            if (pdata && pdata.success) {
                                if (pdata.action_required === 'select_reroll') {
                                    window.__actionInFlight = false;
                                    S.gameState.pendingReroll = true;
                                    S.updateUIForPhase();
                                    if (pdata.dice_details) {
                                        S.showDiceRollModal(pdata.dice_details, pdata.action_name, pdata.attacker_name, pdata.defender_name, true,
                                            pdata.attacker_name && pdata.attacker_name.includes('玩家'),
                                            pdata.defender_name && pdata.defender_name.includes('玩家'));
                                    }
                                    return;
                                }
                                if (pdata.action_required === 'select_effect') {
                                    window.__actionInFlight = false;
                                    S.gameState.pendingEffect = true;
                                    S.updateUIForPhase();
                                    if (pdata.options) S.showEffectSelector(pdata.options);
                                    return;
                                }
                                refreshGameUI();
                            } else if (pdata) {
                                window.__actionInFlight = false;
                                S.showErrorModal('抛射物阶段失败', pdata.message || '未能运行抛射物阶段。');
                            }
                        })
                        .catch(function(e) {
                            window.__actionInFlight = false;
                            S.showErrorModal('抛射物阶段错误', e.message);
                        });
                    }, 1500);
                    return;
                }

                console.log("No action required, refreshing UI via AJAX.");
                refreshGameUI();

            } else {
                console.warn("Operation failed:", data.message);
                window.__actionInFlight = false;
                showErrorModal('操作失败', data.message || '后端返回了一个错误，但没有提供详情。');
            }
        }).catch(e => {
            console.error("Fetch error:", e.message);
            window.__actionInFlight = false;
            showErrorModal('后端通信错误', e.message || '一个未知的fetch错误发生了。');
        });
    }

    // --- AJAX 局部刷新 ---

    function refreshGameUI() {
        fetch(S.apiUrls.gameState || '/api/game_state')
            .then(res => res.json())
            .then(data => {
                if (!data.success) {
                    if (data.redirect) window.location.href = data.redirect;
                    else window.location.reload();
                    return;
                }

                // 更新数据岛
                const gameDataEl = document.getElementById('game-data');
                if (gameDataEl) gameDataEl.textContent = JSON.stringify(data.game_data);

                // 更新 S 命名空间
                const gd = data.game_data;
                S.allEntities = gd.allEntities;
                S.playerID = gd.playerID;
                S.playerEntity = gd.playerEntity;
                S.aiEntity = gd.aiEntity;
                S.orientationMap = gd.orientationMap;
                S.apiUrls = gd.apiUrls;
                S.playerLoadout = gd.playerLoadout;
                S.aiOpponentName = gd.aiOpponentName;

                S.gameState = {
                    turnPhase: S.playerEntity ? S.playerEntity.turn_phase : 'timing',
                    timing: S.playerEntity ? S.playerEntity.timing : null,
                    openingMoveTaken: S.playerEntity ? S.playerEntity.opening_move_taken : false,
                    isPlayerLocked: gd.isPlayerLocked,
                    gameOver: gd.gameOver,
                    pendingEffect: S.playerEntity && S.playerEntity.pending_combat && S.playerEntity.pending_combat.stage && S.playerEntity.pending_combat.stage.includes('EFFECT') ? true : false,
                    pendingReroll: S.playerEntity && S.playerEntity.pending_combat && S.playerEntity.pending_combat.stage && S.playerEntity.pending_combat.stage.includes('REROLL') ? true : false,
                    visualEvents: gd.visualEvents,
                    runProjectilePhase: gd.runProjectilePhase,
                    gameMode: gd.gameMode,
                    defeatCount: gd.defeatCount
                };

                try {
                    // 更新侧边栏 HTML
                    const sidebars = document.querySelectorAll('.sidebar');
                    if (sidebars[0] && data.sidebar_left_html) sidebars[0].innerHTML = data.sidebar_left_html;
                    if (sidebars[1] && data.sidebar_right_html) sidebars[1].innerHTML = data.sidebar_right_html;

                    // 更新棋盘实体 wrappers（新抛射物、已销毁实体、机甲位置等）
                    if (data.board_entities_html) {
                        var entityContainer = document.getElementById('entity-wrappers-container');
                        if (entityContainer) {
                            entityContainer.innerHTML = data.board_entities_html;
                        }
                    }

                    // 更新移动端抽屉（下次打开时重新克隆）
                    const mobileContent = document.getElementById('mobile-drawer-content');
                    if (mobileContent) mobileContent.innerHTML = '';
                    S._drawerPopulated = false;

                    // 清除高亮
                    S.clearHighlights();

                    // 重新初始化棋盘（读取新的 S.allEntities + DOM wrappers）
                    S.initializeBoardVisuals();

                    // 重新绑定侧边栏事件
                    bindSidebarEvents();

                    // 刷新阶段 UI
                    S.updateUIForPhase();

                    // 滚动战斗日志到底部
                    const log = document.querySelector('.combat-log');
                    if (log) log.scrollTop = log.scrollHeight;

                    // 处理视觉事件
                    const events = gd.visualEvents || [];
                    if (events.length > 0) {
                        S.processVisualEvents(events);
                    }

                    // 处理游戏结束
                    if (gd.gameOver) {
                        S.showGameOverModal(gd.gameOver);
                    }
                } catch (domError) {
                    console.error('DOM update in refreshGameUI failed, reloading:', domError);
                    window.location.reload();
                    return;
                }

                window.__actionInFlight = false;
            })
            .catch(e => {
                console.error('AJAX refresh failed, falling back to reload:', e);
                window.location.reload();
            });
    }

    function bindSidebarEvents() {
        // 标签页切换
        const tabBtnActions = document.getElementById('tab-btn-actions');
        const tabBtnStatus = document.getElementById('tab-btn-status');
        const tabPanelActions = document.getElementById('tab-panel-actions');
        const tabPanelStatus = document.getElementById('tab-panel-status');
        if (tabBtnActions) {
            tabBtnActions.addEventListener('click', () => {
                tabBtnActions.classList.add('active');
                if (tabBtnStatus) tabBtnStatus.classList.remove('active');
                if (tabPanelActions) tabPanelActions.style.display = 'block';
                if (tabPanelStatus) tabPanelStatus.style.display = 'none';
            });
        }
        if (tabBtnStatus) {
            tabBtnStatus.addEventListener('click', () => {
                tabBtnStatus.classList.add('active');
                if (tabBtnActions) tabBtnActions.classList.remove('active');
                if (tabPanelStatus) tabPanelStatus.style.display = 'block';
                if (tabPanelActions) tabPanelActions.style.display = 'none';
            });
        }

        // 阶段 1: 时机
        document.getElementById('timing-近战')?.addEventListener('click', () => S.selectTiming('近战'));
        document.getElementById('timing-射击')?.addEventListener('click', () => S.selectTiming('射击'));
        document.getElementById('timing-移动')?.addEventListener('click', () => S.selectTiming('移动'));
        document.getElementById('timing-抛射')?.addEventListener('click', () => S.selectTiming('抛射'));
        document.getElementById('timing-快速')?.addEventListener('click', () => S.selectTiming('快速'));
        document.getElementById('confirm-timing-btn')?.addEventListener('click', S.confirmTiming);

        // 阶段 2: 姿态
        document.getElementById('stance-defense')?.addEventListener('click', () => S.changeStance('defense'));
        document.getElementById('stance-agile')?.addEventListener('click', () => S.changeStance('agile'));
        document.getElementById('stance-attack')?.addEventListener('click', () => S.changeStance('attack'));
        document.getElementById('confirm-stance-btn')?.addEventListener('click', S.confirmStance);

        // 阶段 3: 调整
        document.getElementById('action-adjust-move')?.addEventListener('click', () => S.selectAction('调整移动', 0, 'TP', '', 'system'));
        document.getElementById('action-change-orientation')?.addEventListener('click', () => S.selectAction('仅转向', 0, 'TP', '', 'system'));
        document.getElementById('skip-adjustment-btn')?.addEventListener('click', S.skipAdjustment);

        // 阶段 4: 主动作
        document.querySelectorAll('#phase-main-controls .action-item').forEach(item => {
            const actionName = item.dataset.actionName;
            if (actionName) {
                const actionRange = item.dataset.actionRange;
                const actionType = item.dataset.actionType;
                const actionCost = item.dataset.actionCost;
                const partSlot = item.dataset.partSlot;
                const isJettison = item.dataset.isJettison === 'true';
                item.addEventListener('click', () => {
                    if (item.classList.contains('disabled')) return;
                    if (isJettison) {
                        S.initiateJettison(partSlot);
                    } else {
                        S.selectAction(actionName, parseInt(actionRange, 10), actionType, actionCost, partSlot);
                    }
                });
            }
        });

        // 结束回合
        document.getElementById('end-turn-btn')?.addEventListener('click', () => {
            if (!document.getElementById('end-turn-btn').classList.contains('disabled')) {
                executeEndTurn();
            }
        });

        // 状态标签页部件行点击
        document.querySelectorAll('#tab-panel-status tr[data-part-slot]').forEach(row => {
            row.addEventListener('click', () => {
                S.showPartDetail(row.dataset.controller, row.dataset.partSlot);
            });
        });

        // AI 侧边栏部件行点击
        document.querySelectorAll('.sidebar table tr[data-part-slot][data-controller="ai"]').forEach(row => {
            row.addEventListener('click', () => {
                S.showPartDetail(row.dataset.controller, row.dataset.partSlot);
            });
        });
    }

    function executeEndTurn() {
        if (S.gameState.pendingEffect || S.gameState.pendingReroll) return;
        if (window.__actionInFlight) return;
        window.__actionInFlight = true;

        // 禁用按钮防止重复点击
        document.querySelectorAll('.action-item, .btn, .selector-group button').forEach(el => {
            if (!el.closest('#game-over-modal') && !el.closest('#range-continue-modal') && !el.closest('#error-modal-backdrop')) {
                el.disabled = true;
                el.style.cursor = 'wait';
            }
        });

        fetch(S.apiUrls.endTurnAjax || '/api/end_turn', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({player_id: S.playerID})
        })
        .then(res => res.json())
        .then(data => {
            if (data && data.success) {
                // 处理中断
                if (data.action_required === 'select_reroll') {
                    window.__actionInFlight = false;
                    S.gameState.pendingReroll = true;
                    S.updateUIForPhase();
                    var rd = data;
                    if (rd.dice_details) {
                        var aip = rd.attacker_name && rd.attacker_name.includes('玩家');
                        var dip = rd.defender_name && rd.defender_name.includes('玩家');
                        S.showDiceRollModal(rd.dice_details, rd.action_name, rd.attacker_name, rd.defender_name, true, aip, dip);
                    }
                    return;
                }
                if (data.action_required === 'select_effect') {
                    window.__actionInFlight = false;
                    S.gameState.pendingEffect = true;
                    S.updateUIForPhase();
                    if (data.options) S.showEffectSelector(data.options);
                    return;
                }

                // 需要运行抛射物阶段
                if (data.run_projectile_phase) {
                    setTimeout(function() {
                        fetch(S.apiUrls.runProjectilePhase, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({player_id: S.playerID})
                        })
                        .then(res => res.json())
                        .then(function(pdata) {
                            if (pdata && pdata.success) {
                                if (pdata.action_required === 'select_reroll') {
                                    window.__actionInFlight = false;
                                    S.gameState.pendingReroll = true;
                                    S.updateUIForPhase();
                                    var prd = pdata;
                                    if (prd.dice_details) {
                                        var paip = prd.attacker_name && prd.attacker_name.includes('玩家');
                                        var pdip = prd.defender_name && prd.defender_name.includes('玩家');
                                        S.showDiceRollModal(prd.dice_details, prd.action_name, prd.attacker_name, prd.defender_name, true, paip, pdip);
                                    }
                                    return;
                                }
                                if (pdata.action_required === 'select_effect') {
                                    window.__actionInFlight = false;
                                    S.gameState.pendingEffect = true;
                                    S.updateUIForPhase();
                                    if (pdata.options) S.showEffectSelector(pdata.options);
                                    return;
                                }
                                refreshGameUI();
                            } else if (pdata) {
                                window.__actionInFlight = false;
                                S.showErrorModal('抛射物阶段失败', pdata.message || '后端未能运行抛射物阶段。');
                            }
                        })
                        .catch(function(e) {
                            window.__actionInFlight = false;
                            S.showErrorModal('抛射物阶段错误', e.message);
                        });
                    }, 1500);
                    return;
                }

                refreshGameUI();
            } else if (data) {
                window.__actionInFlight = false;
                S.showErrorModal('结束回合失败', data.message || '后端返回错误。');
            }
        })
        .catch(function(e) {
            window.__actionInFlight = false;
            S.showErrorModal('结束回合错误', e.message);
        });
    }

    function processVisualEvents(events) {
        if (!events || events.length === 0) return;

        const clashEvent = events.find(e => e.type === 'clash_result');
        const rerollEvent = events.find(e => e.type === 'select_reroll');
        const effectEvent = events.find(e => e.type === 'select_effect');
        const diceRollEvent = events.find(e => e.type === 'dice_roll');
        const attackResult = events.find(e => e.type === 'attack_result');

        if (clashEvent) {
            S.showClashModal(clashEvent.details);
            var delay = 3000;
        }

        if (rerollEvent) {
            var rd = rerollEvent.details;
            if (rd.dice_details) {
                var aip = rd.attacker_name.includes('玩家');
                var dip = rd.defender_name.includes('玩家');
                setTimeout(function() {
                    S.showDiceRollModal(rd.dice_details, rd.action_name, rd.attacker_name, rd.defender_name, true, aip, dip);
                }, clashEvent ? 3000 : 0);
            }
        } else if (effectEvent) {
            if (effectEvent.details && effectEvent.details.options) {
                S.showEffectSelector(effectEvent.details.options);
            }
        } else if (diceRollEvent) {
            setTimeout(function() {
                var dd = diceRollEvent;
                S.showDiceRollModal(dd.details, dd.action_name, dd.attacker_name, dd.defender_name, false);
            }, clashEvent ? 3000 : 0);
        } else if (attackResult) {
            S.showAttackEffect(attackResult.defender_pos, attackResult.result_text);
        }
    }
    S.processVisualEvents = processVisualEvents;

    // --- 乐观 UI 函数 ---

    function selectTiming(t) {
        if (S.gameState.pendingEffect || S.gameState.pendingReroll) return;
        if (window.__actionInFlight) return;
        window.__actionInFlight = true;

        fetch(S.apiUrls.selectTiming, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ timing: t, player_id: S.playerID })
        }).then(res => res.json()).then(data => {
            if (!data.success) {
                console.warn('时机同步失败, 强制刷新。');
                window.location.reload();
            } else {
                window.location.reload();
            }
        }).catch(e => { console.error("Fetch error:", e); window.location.reload(); });
    }

    function confirmTiming() {
        if (S.gameState.pendingEffect || S.gameState.pendingReroll) return;
        if (window.__actionInFlight) return;
        window.__actionInFlight = true;
        fetch(S.apiUrls.confirmTiming, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ player_id: S.playerID })
        }).then(res => res.json()).then(data => {
            if (data.success) {
                if (data.clash_occurred) {
                    console.log("Clash occurred! Reloading...");
                    window.location.reload();
                    return;
                }

                S.gameState.turnPhase = 'stance';
                S.playerEntity.turn_phase = 'stance';
                S.updateUIForPhase();
            } else { console.warn('确认时机失败, 强制刷新。'); window.location.reload(); }
        }).catch(e => { console.error("Fetch error:", e); window.location.reload(); })
        .finally(() => { window.__actionInFlight = false; });
    }

    function changeStance(s) {
        if (S.gameState.pendingEffect || S.gameState.pendingReroll) return;
        if (window.__actionInFlight) return;
        window.__actionInFlight = true;
        S.playerEntity.stance = s;
        S.updateUIForPhase();
        fetch(S.apiUrls.changeStance, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ stance: s, player_id: S.playerID })
        }).then(res => res.json()).then(data => {
            if (!data.success) { console.warn('姿态同步失败, 强制刷新。'); window.location.reload(); }
        }).catch(e => { console.error("Fetch error:", e); window.location.reload(); })
        .finally(() => { window.__actionInFlight = false; });
    }

    function confirmStance() {
        if (S.gameState.pendingEffect || S.gameState.pendingReroll) return;
        if (window.__actionInFlight) return;
        window.__actionInFlight = true;
        fetch(S.apiUrls.confirmStance, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ player_id: S.playerID })
        }).then(res => res.json()).then(data => {
            if (data.success) {
                S.gameState.turnPhase = 'adjustment';
                S.playerEntity.turn_phase = 'adjustment';
                S.updateUIForPhase();
            } else { console.warn('确认姿态失败, 强制刷新。'); window.location.reload(); }
        }).catch(e => { console.error("Fetch error:", e); window.location.reload(); })
        .finally(() => { window.__actionInFlight = false; });
    }

    function skipAdjustment() {
        if (S.gameState.pendingEffect || S.gameState.pendingReroll) return;
        if (window.__actionInFlight) return;
        window.__actionInFlight = true;
        fetch(S.apiUrls.skipAdjustment, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ player_id: S.playerID })
        }).then(res => res.json()).then(data => {
            if (data.success) {
                S.gameState.turnPhase = 'main';
                S.playerEntity.turn_phase = 'main';
                S.updateUIForPhase();
            } else { console.warn('跳过调整失败, 强制刷新。'); window.location.reload(); }
        }).catch(e => { console.error("Fetch error:", e); window.location.reload(); })
        .finally(() => { window.__actionInFlight = false; });
    }

    function executeMove() {
        let url = S.selectedAction.isRotationOnly ? S.apiUrls.changeOrientation : (S.selectedAction.name === '调整移动' ? S.apiUrls.executeAdjustMove : S.apiUrls.movePlayer);
        postAndReload(url, {
            action_name: S.selectedAction.name,
            target_pos: S.selectedAction.targetPos,
            final_orientation: S.selectedAction.finalOrientation,
            part_slot: S.selectedAction.slot
        });
    }

    function executeAttack() {
        let body = {
            action_name: S.selectedAction.name,
            part_slot: S.selectedAction.slot,
            target_entity_id: S.selectedAction.targetEntityId,
            target_pos: S.selectedAction.targetPos,
            target_part_name: S.selectedAction.targetPartName
        };
        postAndReload(S.apiUrls.executeAttack, body);
    }

    // --- 暴露到 SMW 的函数 (供 game-board.js / game-combat.js 调用) ---
    S.showErrorModal = showErrorModal;
    S.showGameOverModal = showGameOverModal;
    S.selectAction = selectAction;
    S.initiateJettison = initiateJettison;
    S.initiateAttack = initiateAttack;
    S.initiateLaunch = initiateLaunch;
    S.confirmPartSelection = confirmPartSelection;
    S.postAndReload = postAndReload;
    S.selectTiming = selectTiming;
    S.confirmTiming = confirmTiming;
    S.changeStance = changeStance;
    S.confirmStance = confirmStance;
    S.skipAdjustment = skipAdjustment;
    S.executeMove = executeMove;
    S.executeAttack = executeAttack;

    // --- 3. 初始化和事件绑定 ---

    document.addEventListener('DOMContentLoaded', () => {
        S.updateUIForPhase();
        S.initializeBoardVisuals();

        // 窗口大小变化时重新计算棋盘尺寸
        let resizeDebounce;
        window.addEventListener('resize', () => {
            clearTimeout(resizeDebounce);
            resizeDebounce = setTimeout(() => {
                const oldSize = S.CELL_SIZE_PX;
                updateCellSize();
                if (S.CELL_SIZE_PX !== oldSize) {
                    S.initializeBoardVisuals();
                }
            }, 150);
        });

        // 移动端侧边栏抽屉
        const mobileToggle = document.getElementById('mobile-nav-toggle');
        const mobileSidebar = document.getElementById('mobile-sidebar-drawer');
        const mobileOverlay = document.getElementById('mobile-sidebar-overlay');
        const mobileClose = document.getElementById('mobile-drawer-close');
        const mobileDrawerContent = document.getElementById('mobile-drawer-content');

        if (mobileToggle && mobileSidebar) {
            function populateDrawer() {
                if (S._drawerPopulated) return;
                const sidebars = document.querySelectorAll('.sidebar');
                const leftClone = sidebars[0] ? sidebars[0].cloneNode(true) : null;
                const rightClone = sidebars[1] ? sidebars[1].cloneNode(true) : null;
                if (leftClone) {
                    leftClone.style.display = 'flex';
                    leftClone.style.width = '100%';
                    mobileDrawerContent.appendChild(leftClone);
                }
                if (rightClone) {
                    rightClone.style.display = 'flex';
                    rightClone.style.width = '100%';
                    mobileDrawerContent.appendChild(rightClone);
                }
                S._drawerPopulated = true;
            }

            function openDrawer() {
                populateDrawer();
                mobileSidebar.classList.add('open');
                mobileOverlay.classList.add('open');
            }
            function closeDrawer() {
                mobileSidebar.classList.remove('open');
                mobileOverlay.classList.remove('open');
            }

            mobileToggle.addEventListener('click', openDrawer);
            mobileClose.addEventListener('click', closeDrawer);
            mobileOverlay.addEventListener('click', closeDrawer);
        }

        // 移动端底部结束回合按钮
        const mobileEndTurnBtn = document.getElementById('mobile-end-turn-btn');
        if (mobileEndTurnBtn) {
            mobileEndTurnBtn.addEventListener('click', () => {
                if (!mobileEndTurnBtn.classList.contains('disabled')) {
                    executeEndTurn();
                }
            });
        }

        partDetailModalBackdrop = document.getElementById('part-detail-modal-backdrop');
        partDetailTitle = document.getElementById('part-detail-title');
        partDetailImage = document.getElementById('part-detail-image');
        partDetailStatsContainer = document.getElementById('part-detail-stats-container');
        partDetailStatsList = document.getElementById('part-detail-stats-list');
        partDetailActionsList = document.getElementById('part-detail-actions-list');

        if (S.gameState.gameOver) {
            showGameOverModal(S.gameState.gameOver);
        }

        const log = document.querySelector('.combat-log');
        if (log) log.scrollTop = log.scrollHeight;

        if (S.gameState.runProjectilePhase && !S.gameState.gameOver && !S.gameState.pendingEffect && !S.gameState.pendingReroll) {
            document.querySelectorAll('.action-item, .btn, .selector-group button').forEach(el => {
                if (!el.closest('#game-over-modal') && !el.closest('#range-continue-modal') && !el.closest('#error-modal-backdrop')) {
                    el.disabled = true;
                    el.style.cursor = 'wait';
                }
            });
            setTimeout(() => {
                fetch(S.apiUrls.runProjectilePhase, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ player_id: S.playerID })
                })
                .then(res => res.json())
                .then(data => {
                    if (data && data.success) {
                        if (data.action_required === 'select_reroll') {
                            console.log("Projectile Phase: Action required: select_reroll. Showing modal.");
                            const rerollData = data;
                            if (!rerollData.dice_details) {
                                console.error("Reroll interrupt missing dice_details!", rerollData);
                                showErrorModal('前端错误', '重投中断缺少 dice_details，无法显示弹窗。');
                                return;
                            }
                            const attackerIsPlayer = (rerollData.attacker_name.includes("玩家"));
                            const defenderIsPlayer = (rerollData.defender_name.includes("玩家"));
                            S.showDiceRollModal(
                                rerollData.dice_details,
                                rerollData.action_name,
                                rerollData.attacker_name,
                                rerollData.defender_name,
                                true,
                                attackerIsPlayer,
                                defenderIsPlayer
                            );
                            S.gameState.pendingReroll = true;
                            S.updateUIForPhase();
                            return;
                        }

                        if (data.action_required === 'select_effect') {
                            console.log("Projectile Phase: Action required: select_effect. Showing modal.");
                            if (!data.options) {
                                console.error("Effect interrupt missing options!", data);
                                showErrorModal('前端错误', '效果中断缺少 options，无法显示弹窗。');
                                return;
                            }
                            S.showEffectSelector(data.options);
                            S.gameState.pendingEffect = true;
                            S.updateUIForPhase();
                            return;
                        }

                        console.log("Projectile phase complete, no interrupts. Refreshing UI for player turn.");
                        refreshGameUI();

                    } else if (data) {
                        console.error("抛射物阶段运行失败:", data.message);
                        showErrorModal('抛射物阶段失败', data.message || '后端未能运行抛射物阶段。');
                    }
                })
                .catch(e => {
                    console.error("Fetch error:", e);
                    showErrorModal('抛射物阶段Fetch失败', e.message || '无法连接到服务器以运行抛射物阶段。');
                });
            }, 2000);
        }

        S.processVisualEvents(S.gameState.visualEvents);

        // 状态不一致检测
        const rerollEvent = S.gameState.visualEvents.find(e => e.type === 'select_reroll');
        const effectEvent = S.gameState.visualEvents.find(e => e.type === 'select_effect');
        if (S.gameState.pendingReroll && !rerollEvent) {
            showErrorModal('状态不同步', '检测到状态不同步 (pendingReroll=true 但缺少事件)。将尝试强制重载。');
            setTimeout(() => window.location.reload(), 3000);
        }
        if (S.gameState.pendingEffect && !effectEvent) {
            showErrorModal('状态不同步', '检测到状态不同步 (pendingEffect=true 但缺少事件)。将尝试强制重载。');
            setTimeout(() => window.location.reload(), 3000);
        }

        // --- 绑定侧边栏 UI 事件 ---
        bindSidebarEvents();

        // 弹窗事件 — 函数来自 game-board.js / game-combat.js，通过 S 访问
        document.getElementById('part-selector-cancel-btn')?.addEventListener('click', S.closePartSelector);
        document.getElementById('dice-roll-close')?.addEventListener('click', S.closeDiceRollModal);
        document.getElementById('dice-roll-skip')?.addEventListener('click', () => S.confirmReroll(true));
        document.getElementById('dice-roll-confirm')?.addEventListener('click', () => S.confirmReroll(false));

        // 为重投骰子添加事件委托
        const attackerDiceGroup = document.getElementById('dice-roll-attacker-result');
        const defenderDiceGroup = document.getElementById('dice-roll-defender-result');

        const handleDieClick = (event) => {
            const dieElement = event.target.closest('.dice-reroll-group');
            if (dieElement && dieElement.dataset.clickable === "true") {
                S.toggleRerollDie(dieElement);
            }
        };

        attackerDiceGroup?.addEventListener('click', handleDieClick);
        defenderDiceGroup?.addEventListener('click', handleDieClick);

        // 部件详情
        document.getElementById('part-detail-modal-backdrop')?.addEventListener('click', S.closePartDetailModal);
        document.getElementById('part-detail-close-btn')?.addEventListener('click', S.closePartDetailModal);
        document.getElementById('part-detail-modal')?.addEventListener('click', (e) => e.stopPropagation());

        // 为"状态"标签页中的玩家部件行添加点击事件
        document.querySelectorAll('#tab-panel-status tr[data-part-slot]').forEach(row => {
            row.addEventListener('click', () => {
                S.showPartDetail(row.dataset.controller, row.dataset.partSlot);
            });
        });
        document.querySelectorAll('.sidebar table tr[data-part-slot][data-controller="ai"]').forEach(row => {
            row.addEventListener('click', () => {
                S.showPartDetail(row.dataset.controller, row.dataset.partSlot);
            });
        });

        // 方向选择器
        document.getElementById('orientation-N')?.addEventListener('click', () => S.setFinalOrientation('N'));
        document.getElementById('orientation-E')?.addEventListener('click', () => S.setFinalOrientation('E'));
        document.getElementById('orientation-S')?.addEventListener('click', () => S.setFinalOrientation('S'));
        document.getElementById('orientation-W')?.addEventListener('click', () => S.setFinalOrientation('W'));
    });

})();

// --- 1. 状态初始化 ---

// 从 HTML 中的 "data island" 脚本标签读取由 Jinja 注入的数据
const gameDataElement = document.getElementById('game-data');
const data = JSON.parse(gameDataElement.textContent);

// 模块内的"全局"状态变量
let selectedAction = {};
const CELL_SIZE_PX = 51; // 50px + 1px gap
let diceModalTimer = null;

// 从 data 对象解构所有动态数据
const allEntities = data.allEntities;
const playerID = data.playerID;
const playerEntity = data.playerEntity;
const aiEntity = data.aiEntity;
const orientationMap = data.orientationMap;
const apiUrls = data.apiUrls; // 所有 Flask URL
const playerLoadout = data.playerLoadout;
const aiOpponentName = data.aiOpponentName;

// 这是我们将引用的主要前端状态机
const gameState = {
    turnPhase: playerEntity ? playerEntity.turn_phase : 'timing',
    timing: playerEntity ? playerEntity.timing : null,
    openingMoveTaken: playerEntity ? playerEntity.opening_move_taken : false,
    isPlayerLocked: data.isPlayerLocked,
    gameOver: data.gameOver,
    pendingEffect: playerEntity && playerEntity.pending_effect_data ? true : false,
    pendingReroll: playerEntity && playerEntity.pending_reroll_data ? true : false,
    visualEvents: data.visualEvents,
    runProjectilePhase: data.runProjectilePhase,
    gameMode: data.gameMode,
    defeatCount: data.defeatCount
};

// 静态常量
const effectDescriptions = {
    'devastating': { title: '【毁伤】', text: '对目标结构造成二次伤害', style: 'background-color: var(--status-damaged);' },
    'scattershot': { title: '【霰射】', text: '对随机部件造成溢出伤害', style: 'background-color: var(--status-destroyed);' },
    'cleave': { title: '【顺劈】', text: '对随机部件造成溢出伤害', style: 'background-color: #805ad5;' }
};
const diceIconMap = {
    '重击': 'H', '轻击': 'L', '防御': 'D', '闪避': 'E',
    '空心重击': 'h', '空心轻击': 'l', '空心防御': 'd',
    '闪电': '⚡', '眼睛': '👁', '空白': ' '
};
const diceColorMap = {
    'yellow_count': 'yellow', 'red_count': 'red', 'white_count': 'white', 'blue_count': 'blue'
};

// 缓存 DOM 元素
let partDetailModalBackdrop, partDetailTitle, partDetailImage, partDetailStatsContainer, partDetailStatsList, partDetailActionsList;

// --- 2. 核心函数 (从旧 <script> 块复制而来) ---

function initializeBoardVisuals() {
    if (!allEntities) return;
    const wrappers = document.querySelectorAll('.mech-icon-wrapper');
    wrappers.forEach(wrapper => {
        try {
            const entityId = wrapper.id.replace('entity-', '').replace('-wrapper', '');
            const entityData = allEntities.find(e => e.id === entityId);
            if (!entityData) return;

            const img = document.getElementById(`img-${entityId}`);
            if (!img) return;

            const lastPos = JSON.parse(wrapper.dataset.lastPos);
            const currentPos = JSON.parse(wrapper.dataset.currentPos);

            const defaultScaleX = (entityData.controller === 'ai') ? -1 : 1;
            let desiredScaleX = defaultScaleX;
            let desiredRotation = 0;
            const orientation = entityData.orientation;

            if (orientation === 'W') {
                desiredScaleX = -1;
            } else if (orientation === 'E') {
                desiredScaleX = 1;
            } else if (orientation === 'N') {
                desiredScaleX = defaultScaleX;
                desiredRotation = -90;
            } else if (orientation === 'S') {
                desiredScaleX = defaultScaleX;
                desiredRotation = 90;
            }

            const finalTransform = `scaleX(${desiredScaleX}) rotate(${desiredRotation}deg)`;
            const finalLeft = `${(currentPos[0] - 1) * CELL_SIZE_PX}px`;
            const finalTop = `${(currentPos[1] - 1) * CELL_SIZE_PX}px`;

            if (lastPos && (lastPos[0] !== currentPos[0] || lastPos[1] !== currentPos[1])) {
                const startLeft = `${(lastPos[0] - 1) * CELL_SIZE_PX}px`;
                const startTop = `${(lastPos[1] - 1) * CELL_SIZE_PX}px`;

                wrapper.style.transition = 'none';
                img.style.transition = 'transform 0.3s ease';
                img.style.transform = finalTransform;
                wrapper.style.left = startLeft;
                wrapper.style.top = startTop;

                wrapper.offsetHeight; // 强制重绘

                if (entityData.entity_type === 'projectile') {
                    wrapper.style.transition = 'left 0.8s linear, top 0.8s linear';
                } else {
                    wrapper.style.transition = 'left 0.4s ease-out, top 0.4s ease-out';
                }
                wrapper.style.left = finalLeft;
                wrapper.style.top = finalTop;
            } else {
                wrapper.style.transition = 'none';
                img.style.transition = 'none';
                wrapper.style.left = finalLeft;
                wrapper.style.top = finalTop;
                img.style.transform = finalTransform;

                wrapper.offsetHeight;

                if (entityData.entity_type === 'projectile') {
                    wrapper.style.transition = 'left 0.8s linear, top 0.8s linear';
                } else {
                    wrapper.style.transition = 'left 0.4s ease-out, top 0.4s ease-out';
                }
                img.style.transition = 'transform 0.3s ease';
            }
        } catch (e) {
            console.error("解析或定位实体时出错:", e, wrapper.id);
        }
    });
}

function showAttackEffect(pos, text) {
    const [x, y] = pos;
    const cell = document.getElementById(`cell-${x}-${y}`);
    if (!cell) return;

    if (text === '击穿' || text === 'effect_choice_required') {
        const explosion = document.createElement('div');
        explosion.className = 'explosion-effect';
        cell.appendChild(explosion);
        setTimeout(() => { if (explosion.parentNode) { explosion.parentNode.removeChild(explosion); } }, 800);
    }

    const indicator = document.createElement('div');
    indicator.className = 'damage-indicator';
    if (text === '击穿') {
        indicator.innerText = '击穿!';
        indicator.classList.add('hit');
    } else if (text === '无效') {
        indicator.innerText = '无效';
        indicator.classList.add('miss');
    }

    if (indicator.innerText) {
        cell.appendChild(indicator);
        setTimeout(() => { if (indicator.parentNode) { indicator.parentNode.removeChild(indicator); } }, 1200);
    }
}

function showGameOverModal(status) {
    if (window.recordGameOutcome) {
        window.recordGameOutcome(status, playerLoadout, aiOpponentName);
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
            if (gameState.gameMode === 'horde') { title.innerText = `结束\n最终击败数: ${gameState.defeatCount}`; }
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

function updateUIForPhase() {
    if (gameState.gameOver || !playerEntity || !playerEntity.turn_phase) return;

    if (playerEntity.stance === 'downed') {
        ['timing', 'stance', 'adjustment', 'main'].forEach(phase => {
            const el = document.getElementById(`phase-${phase}-controls`);
            if (el) el.style.display = 'none';
        });
        const endTurnBtn = document.getElementById('end-turn-btn');
        if(endTurnBtn) {
            endTurnBtn.classList.add('disabled');
            endTurnBtn.title = '机甲宕机中，无法行动';
            document.getElementById('end-turn-form').onsubmit = (e) => { e.preventDefault(); return false; };
        }
        return;
    }

    ['timing', 'stance', 'adjustment', 'main'].forEach(phase => {
        const el = document.getElementById(`phase-${phase}-controls`);
        if (el) el.style.display = gameState.turnPhase === phase ? 'block' : 'none';
    });

    if (gameState.turnPhase === 'timing') {
        document.querySelectorAll('#phase-timing-controls button').forEach(btn => {
            btn.classList.toggle('active', btn.textContent === gameState.timing);
        });
    }
    if (gameState.turnPhase === 'stance') {
        document.querySelectorAll('#phase-stance-controls button').forEach(btn => {
            btn.classList.toggle('active', btn.id.includes(playerEntity.stance));
        });
    }

    const message = gameState.pendingReroll ? '请先解决重投！' : '请先选择效果！';
    const isInterrupted = gameState.pendingEffect || gameState.pendingReroll;

    document.querySelectorAll('#phase-main-controls .action-item, #phase-adjustment-controls .action-item, #end-turn-btn').forEach(item => {
        if (isInterrupted) {
            item.classList.add('disabled');
            item.title = message;
            return; // 立即禁用并返回
        }

        let isDisabled = false;
        let title = '';
        const baseTitle = item.getAttribute('title') || '';

        if (baseTitle === '本回合已使用') {
            isDisabled = true; title = '本回合已使用';
        } else if (baseTitle === '弹药耗尽') {
            isDisabled = true; title = '弹药耗尽';
        } else if (gameState.turnPhase === 'main') {
            if (!gameState.openingMoveTaken && item.dataset.actionType !== gameState.timing) {
                isDisabled = true; title = '非当前时机的起手动作';
            }
            if (gameState.isPlayerLocked && item.dataset.actionType === '射击') {
                isDisabled = true; title = '被近战锁定，无法射击';
            }
        }

        item.classList.toggle('disabled', isDisabled);
        item.title = title;
    });
}


function clearHighlights() {
    document.querySelectorAll('.grid-cell').forEach(c => {
        c.classList.remove('highlight-move', 'highlight-attack', 'highlight-launch');
        c.onclick = null;
    });
    const orientationSelector = document.getElementById('orientation-selector');
    if (orientationSelector.parentElement !== document.body) {
         document.body.appendChild(orientationSelector);
    }
    orientationSelector.style.display = 'none';
}

function selectAction(name, range, type, cost, partSlot) {
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    clearHighlights();
    selectedAction = { name, range, type, cost, slot: partSlot, player_id: playerID };

    let url = '', body = { action_name: name, part_slot: partSlot, player_id: playerID };

    if (type === '移动' || name === '调整移动') {
        url = apiUrls.getMoveRange;
    } else if (type === '近战' || type === '射击' || type === '抛射' || type === '快速') {
        url = apiUrls.getAttackRange;
    } else if (name === '仅转向') {
        showOrientationSelector(playerEntity.pos[0], playerEntity.pos[1], true);
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
                    c.onclick = () => showOrientationSelector(x,y);
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
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    clearHighlights();
    postAndReload(apiUrls.jettisonPart, {
        action_name: '【弃置】',
        part_slot: partSlot
    });
}

function initiateAttack(entityId, x, y, isBackAttack) {
    selectedAction.targetEntityId = entityId;
    selectedAction.targetPos = [x, y];
    executeAttack();
}

function initiateLaunch(x, y) {
    selectedAction.targetEntityId = null;
    selectedAction.targetPos = [x, y];
    executeAttack();
}

function showPartSelector() {
    const modal = document.getElementById('part-selector-modal'), buttons = document.getElementById('part-buttons'); buttons.innerHTML = '';
    if (!aiEntity || !aiEntity.parts) return;

    for (const slot in aiEntity.parts) {
        const part = aiEntity.parts[slot];
        if (part && part.status !== 'destroyed') {
            const btn = document.createElement('button');
            btn.className = 'btn'; btn.style.backgroundColor = 'var(--primary-color)';
            btn.innerText = `${part.name} (${slot})`;
            btn.onclick = () => confirmPartSelection(slot);
            buttons.appendChild(btn);
        }
    }
    modal.style.display = 'block';
}

function closePartSelector() { document.getElementById('part-selector-modal').style.display = 'none'; clearHighlights(); }

function confirmPartSelection(partSlot) {
    selectedAction.targetPartName = partSlot;
    closePartSelector();
    executeAttack();
}

function showEffectSelector(options) {
    const buttonsDiv = document.getElementById('effect-buttons'); buttonsDiv.innerHTML = '';
    if (!options || options.length === 0) { console.error("showEffectSelector 被调用，但没有提供选项！"); return; }
    options.forEach(optionKey => {
        const desc = effectDescriptions[optionKey];
        if (desc) {
            const btn = document.createElement('button'); btn.className = 'btn'; btn.style.cssText = desc.style || 'background-color: var(--primary-color);';
            btn.innerHTML = `<strong>${desc.title}</strong><br><small>${desc.text}</small>`;
            btn.onclick = () => confirmEffectChoice(optionKey);
            buttonsDiv.appendChild(btn);
        } else { console.warn(`未知的效果键: ${optionKey}`); }
    });
    document.getElementById('effect-selector-modal').style.display = 'block';
}

function confirmEffectChoice(choice) {
    document.getElementById('effect-selector-modal').style.display = 'none';
    postAndReload(apiUrls.resolveEffectChoice, { choice: choice, player_id: playerID });
}

function showOrientationSelector(x, y, isRotationOnly = false) {
    const cell = document.getElementById(`cell-${x}-${y}`);
    const s = document.getElementById('orientation-selector');
    if (cell) {
        cell.appendChild(s);
    } else {
        document.getElementById('game-board').appendChild(s);
    }
    s.style.display = 'flex';
    selectedAction.targetPos = [x, y];
    selectedAction.isRotationOnly = isRotationOnly;
}

function setFinalOrientation(o) { selectedAction.finalOrientation = o; executeMove(); }

function postAndReload(url, body = {}) {
    body.player_id = playerID;

    fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })
    .then(res => {
        if (res.redirected) {
            window.location.href = res.url;
            return null;
        }
        if (!res.ok) { throw new Error(`HTTP error! status: ${res.status}`); }
        return res.json();
    })
    .then(data => {
        if (!data) return;

        if(data.success) {
            if (data.action_required === 'select_part') { showPartSelector(); }
            else if (data.action_required === 'select_reroll') {
                const rerollData = data;
                const attackerIsPlayer = (rerollData.attacker_name.includes("玩家"));
                const defenderIsPlayer = (rerollData.defender_name.includes("玩家"));
                showDiceRollModal(
                    rerollData.dice_details,
                    rerollData.action_name,
                    rerollData.attacker_name,
                    rerollData.defender_name,
                    true,
                    attackerIsPlayer,
                    defenderIsPlayer
                );
            }
            else if (data.action_required === 'select_effect') { showEffectSelector(data.options); }
            else { window.location.reload(); }
        } else {
            console.warn("操作失败: " + data.message);
            if (data.message.includes("必须先解决重投")) {
                 console.error(
                    "--- [错误类型判断] ---",
                    "\n操作失败！",
                    "\n原因: gameState.pendingReroll (后端) 为 true。",
                    "\n这通常意味着前端状态与后端不同步，或者骰子弹窗没有正确显示。",
                    "\n请检查上一个 'reroll_required' 事件是否被正确处理。"
                );
            }
            window.location.reload();
        }
    }).catch(e => {
        console.error("Fetch error:", e);
        window.location.reload();
    });
}

// --- [MODIFIED] 乐观 UI 函数 ---

function selectTiming(t) {
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    gameState.timing = t;
    playerEntity.timing = t;
    updateUIForPhase();
    fetch(apiUrls.selectTiming, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ timing: t, player_id: playerID })
    }).then(res => res.json()).then(data => {
        if (!data.success) { console.warn('时机同步失败, 强制刷新。'); window.location.reload(); }
    }).catch(e => { console.error("Fetch error:", e); window.location.reload(); });
}

function confirmTiming() {
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    fetch(apiUrls.confirmTiming, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ player_id: playerID })
    }).then(res => res.json()).then(data => {
        if (data.success) {
            gameState.turnPhase = 'stance';
            playerEntity.turn_phase = 'stance';
            updateUIForPhase();
        } else { console.warn('确认时机失败, 强制刷新。'); window.location.reload(); }
    }).catch(e => { console.error("Fetch error:", e); window.location.reload(); });
}

function changeStance(s) {
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    playerEntity.stance = s;
    updateUIForPhase();
    fetch(apiUrls.changeStance, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ stance: s, player_id: playerID })
    }).then(res => res.json()).then(data => {
        if (!data.success) { console.warn('姿态同步失败, 强制刷新。'); window.location.reload(); }
    }).catch(e => { console.error("Fetch error:", e); window.location.reload(); });
}

function confirmStance() {
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    fetch(apiUrls.confirmStance, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ player_id: playerID })
    }).then(res => res.json()).then(data => {
        if (data.success) {
            gameState.turnPhase = 'adjustment';
            playerEntity.turn_phase = 'adjustment';
            updateUIForPhase();
        } else { console.warn('确认姿态失败, 强制刷新。'); window.location.reload(); }
    }).catch(e => { console.error("Fetch error:", e); window.location.reload(); });
}

function skipAdjustment() {
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    fetch(apiUrls.skipAdjustment, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ player_id: playerID })
    }).then(res => res.json()).then(data => {
        if (data.success) {
            gameState.turnPhase = 'main';
            playerEntity.turn_phase = 'main';
            updateUIForPhase();
        } else { console.warn('跳过调整失败, 强制刷新。'); window.location.reload(); }
    }).catch(e => { console.error("Fetch error:", e); window.location.reload(); });
}

// --- 其他函数 (从旧 <script> 块复制而来) ---

function executeMove() {
    let url = selectedAction.isRotationOnly ? apiUrls.changeOrientation : (selectedAction.name === '调整移动' ? apiUrls.executeAdjustMove : apiUrls.movePlayer);
    postAndReload(url, {
        action_name: selectedAction.name,
        target_pos: selectedAction.targetPos,
        final_orientation: selectedAction.finalOrientation,
        part_slot: selectedAction.slot
    });
}

function executeAttack() {
    let body = {
        action_name: selectedAction.name,
        part_slot: selectedAction.slot,
        target_entity_id: selectedAction.targetEntityId,
        target_pos: selectedAction.targetPos,
        target_part_name: selectedAction.targetPartName
    };
    postAndReload(apiUrls.executeAttack, body);
}

function showPartDetail(controller, slot) {
    if (!allEntities) return;
    let mech = (controller === 'player') ? playerEntity : aiEntity;
    if (!mech || !mech.parts || !mech.parts[slot]) {
        console.warn(`Could not find part for ${controller} at ${slot}`);
        return;
    }
    const part = mech.parts[slot];
    if (!part) return; // 如果部件为空 (例如已被摧毁且数据中不存在)

    partDetailTitle.innerText = part.name;
    let statsHtml = `<li>装甲: ${part.armor}</li><li>结构: ${part.structure}</li>`;
    if (part.evasion) statsHtml += `<li>闪避: ${part.evasion}</li>`;
    if (part.electronics) statsHtml += `<li>电子: ${part.electronics}</li>`;
    if (part.parry) statsHtml += `<li>招架: ${part.parry}</li>`;
    if (part.adjust_move) statsHtml += `<li>调整移动: ${part.adjust_move}</li>`;
    partDetailStatsList.innerHTML = statsHtml;

    let actionsHtml = '';
    if (part.actions && part.actions.length > 0) {
        part.actions.forEach(action => {
            let costStr = '';
            if (action.cost === 'L') costStr = '2 AP + 1 TP';
            else if (action.cost === 'M') costStr = '2 AP';
            else if (action.cost === 'S') costStr = '1 AP';
            else if (action.action_type === '被动') costStr = '被动';
            else costStr = action.cost;
            let details = `(${action.action_type}, ${costStr})`;
            if (action.dice) details += `, ${action.dice}`;
            if (action.range_val > 0) details += `, R: ${action.range_val}`;
            actionsHtml += `<div class="part-detail-action"><strong>${action.name}</strong><small>${details}</small></div>`;
        });
    } else {
        actionsHtml = '<span>无</span>';
    }
    partDetailActionsList.innerHTML = actionsHtml;

    if (part.image_url) {
        partDetailImage.src = part.image_url;
        partDetailImage.style.display = 'block';
        partDetailStatsContainer.style.display = 'none';
    } else {
        partDetailImage.style.display = 'none';
        partDetailStatsContainer.style.display = 'block';
    }
    partDetailModalBackdrop.style.display = 'flex';
}

function closePartDetailModal() {
    if (partDetailModalBackdrop) {
        partDetailModalBackdrop.style.display = 'none';
    }
}

function formatDiceInput(input) {
    let html = ''; if (!input) return '<span>无</span>';
    for (const key in input) {
        const color = diceColorMap[key]; const count = input[key];
        if (count > 0 && color) {
            for(let i=0; i < count; i++) { html += `<span class="dice-icon dice-input ${color}">${key.charAt(0).toUpperCase()}</span>`; }
        }
    }
    return html || '<span>无</span>';
}

function formatDiceResult(result, rollType, isClickable = false) {
    let html = '';
    if (!result || Object.keys(result).length === 0) return '<span>无结果</span>';
    const color_order = ['yellow', 'red', 'white', 'blue'];
    let total_dice_groups_rendered = 0;

    for (const color_key of color_order) {
        const dice_groups = result[color_key];
        if (dice_groups && dice_groups.length > 0) {
            for (const [die_index, die_results] of dice_groups.entries()) {
                if (total_dice_groups_rendered > 0) {
                     html += `<span style="border-left: 2px solid var(--border-color); margin: 0 0.5rem; height: 1.5rem;"></span>`;
                }
                let dieGroupHtml = '';
                for (const key of die_results) {
                    const icon = diceIconMap[key] || '?';
                    dieGroupHtml += `<span class="dice-icon dice-result ${key}">${icon}</span>`;
                }

                // [MODIFIED] 移除内联 onclick, 替换为 data-clickable
                const clickableClass = isClickable ? 'clickable' : 'disabled';
                html += `<span class="dice-reroll-group ${clickableClass}"
                              data-roll-type="${rollType}"
                              data-color="${color_key}"
                              data-index="${die_index}"
                              ${isClickable ? `data-clickable="true"` : ''}>
                          ${dieGroupHtml}
                         </span>`;
                total_dice_groups_rendered++;
            }
        }
    }
    return html || '<span>无结果</span>';
}


function showDiceRollModal(diceDetails, actionName, attackerName, defenderName, isInteractive = false, attackerIsPlayer = false, defenderIsPlayer = false) {
    if (diceModalTimer) {
        clearTimeout(diceModalTimer);
        diceModalTimer = null;
    }

    document.getElementById('dice-roll-title').innerText = `掷骰结算: ${actionName || 'Attack'}`;
    document.getElementById('dice-roll-attacker-name').innerText = attackerName || '攻击方';
    document.getElementById('dice-roll-defender-name').innerText = defenderName || '防御方';

    const details = diceDetails;

    document.getElementById('dice-roll-attacker-input').innerHTML = formatDiceInput(details.attack_dice_input);
    document.getElementById('dice-roll-attacker-result').innerHTML = formatDiceResult(details.attack_dice_result, 'attacker', isInteractive && attackerIsPlayer);

    document.getElementById('dice-roll-defender-input').innerHTML = formatDiceInput(details.defense_dice_input);
    document.getElementById('dice-roll-defender-result').innerHTML = formatDiceResult(details.defense_dice_result, 'defender', isInteractive && defenderIsPlayer);

    const secondarySection = document.getElementById('dice-roll-secondary-section');
    if (details.secondary_roll) {
        const secondary = details.secondary_roll;
        let title = "效果结算";
        if (secondary.type === 'devastating_roll') title = "【毁伤】结算";
        if (secondary.type === 'scattershot_roll') title = "【霰射】结算";
        if (secondary.type === 'cleave_roll') title = "【顺劈】结算";
        document.getElementById('dice-roll-secondary-title').innerText = title;
        document.getElementById('dice-roll-secondary-input').innerHTML = formatDiceInput(secondary.defense_dice_input);
        document.getElementById('dice-roll-secondary-result').innerHTML = formatDiceResult(secondary.defense_dice_result, 'secondary', false);
        secondarySection.style.display = 'block';
    } else {
        secondarySection.style.display = 'none';
    }

    const playerLinkPoints = (playerEntity && playerEntity.pilot) ? playerEntity.pilot.link_points : 0;
    const canReroll = playerLinkPoints > 0;

    const rerollButtons = document.getElementById('dice-roll-buttons-reroll');
    const closeButton = document.getElementById('dice-roll-buttons-default');
    const confirmButton = document.getElementById('dice-roll-confirm');
    const skipButton = document.getElementById('dice-roll-skip');

    if (isInteractive) {
        rerollButtons.classList.remove('reroll-hidden');
        closeButton.classList.add('reroll-hidden');

        if (canReroll) {
            confirmButton.classList.remove('disabled');
            confirmButton.disabled = false;
            document.getElementById('reroll-link-cost').innerText = '1';
        } else {
            confirmButton.classList.add('disabled');
            confirmButton.disabled = true;
            document.getElementById('reroll-link-cost').innerText = '0';
        }
        skipButton.classList.remove('disabled');
        skipButton.disabled = false;
    } else {
        rerollButtons.classList.add('reroll-hidden');
        closeButton.classList.remove('reroll-hidden');
        diceModalTimer = setTimeout(closeDiceRollModal, 5000);
    }

    document.getElementById('dice-roll-modal-backdrop').style.display = 'flex';
}

// [MODIFIED] 这现在是事件委托的目标
function toggleRerollDie(element) {
    if (element.dataset.clickable !== "true") return;
    element.classList.toggle('selected');
}

function confirmReroll(isSkipping = false) {
    let selections_attacker = [];
    let selections_defender = [];

    if (!isSkipping) {
        document.querySelectorAll('#dice-roll-attacker-result .dice-reroll-group.selected').forEach(die => {
            selections_attacker.push({
                color: die.dataset.color,
                index: parseInt(die.dataset.index, 10)
            });
        });
        document.querySelectorAll('#dice-roll-defender-result .dice-reroll-group.selected').forEach(die => {
            selections_defender.push({
                color: die.dataset.color,
                index: parseInt(die.dataset.index, 10)
            });
        });
    }

    closeDiceRollModal();
    postAndReload(apiUrls.resolveReroll, {
        reroll_selections_attacker: selections_attacker,
        reroll_selections_defender: selections_defender
    });
}

function closeDiceRollModal() {
    if (diceModalTimer) {
        clearTimeout(diceModalTimer);
        diceModalTimer = null;
    }
    document.getElementById('dice-roll-modal-backdrop').style.display = 'none';
    if (!gameState.pendingReroll) {
        const firstAttackResult = gameState.visualEvents.find(e => e.type === 'attack_result');
        if (firstAttackResult && !gameState.runProjectilePhase) {
            showAttackEffect(firstAttackResult.defender_pos, firstAttackResult.result_text);
        }
    }
}

// --- 3. 初始化和事件绑定 ---

document.addEventListener('DOMContentLoaded', () => {
    // 初始化
    updateUIForPhase();
    initializeBoardVisuals();

    // 缓存部件详情弹窗的 DOM 元素
    partDetailModalBackdrop = document.getElementById('part-detail-modal-backdrop');
    partDetailTitle = document.getElementById('part-detail-title');
    partDetailImage = document.getElementById('part-detail-image');
    partDetailStatsContainer = document.getElementById('part-detail-stats-container');
    partDetailStatsList = document.getElementById('part-detail-stats-list');
    partDetailActionsList = document.getElementById('part-detail-actions-list');

    // 检查游戏结束
    if (gameState.gameOver) {
        showGameOverModal(gameState.gameOver);
    }

    // 检查待处理效果
    if (gameState.pendingEffect) {
        const pendingOptions = (playerEntity.pending_effect_data && playerEntity.pending_effect_data.options) ? playerEntity.pending_effect_data.options : [];
        showEffectSelector(pendingOptions);
    }

    // 滚动日志到底部
    const log = document.querySelector('.combat-log');
    if (log) log.scrollTop = log.scrollHeight;

    // AI 回合暂停逻辑
    if (gameState.runProjectilePhase && !gameState.gameOver && !gameState.pendingEffect && !gameState.pendingReroll) {
        document.querySelectorAll('.action-item, .btn, .selector-group button').forEach(el => {
            if (!el.closest('#game-over-modal') && !el.closest('#range-continue-modal')) {
                el.disabled = true;
                el.style.cursor = 'wait';
            }
        });
        setTimeout(() => {
            fetch(apiUrls.runProjectilePhase, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({})
            })
            .then(res => {
                if (res.redirected) { window.location.href = res.url; } else { return res.json(); }
            })
            .then(data => {
                if (data && data.success) { window.location.reload(); }
                else if (data) { console.error("抛射物阶段运行失败:", data.message); window.location.reload(); }
            })
            .catch(e => { console.error("Fetch error:", e); window.location.reload(); });
        }, 2000);
    }

    // 视觉事件处理
    const rerollEvent = gameState.visualEvents.find(e => e.type === 'reroll_required');
    const diceRollEvent = gameState.visualEvents.find(e => e.type === 'dice_roll');
    const firstAttackResult = gameState.visualEvents.find(e => e.type === 'attack_result');

    if (rerollEvent) {
        const rerollData = rerollEvent.details;
        const attackerIsPlayer = (rerollData.attacker_name.includes("玩家"));
        const defenderIsPlayer = (rerollData.defender_name.includes("玩家"));
        showDiceRollModal(
            rerollData.dice_details, rerollData.action_name,
            rerollData.attacker_name, rerollData.defender_name,
            true, attackerIsPlayer, defenderIsPlayer
        );
    } else if (diceRollEvent) {
        const eventData = diceRollEvent;
        showDiceRollModal(
            eventData.details, eventData.action_name,
            eventData.attacker_name, eventData.defender_name,
            false
        );
    } else if (firstAttackResult) {
        showAttackEffect(firstAttackResult.defender_pos, firstAttackResult.result_text);
    }

    // 调试日志
    if (gameState.pendingReroll && !rerollEvent) {
        console.error(
            "--- [错误类型判断] ---",
            "\n游戏卡死！",
            "\n原因: gameState.pendingReroll 为 true (红色警告条出现)，",
            "但是 gameState.visualEvents 中 *没有* 找到 'reroll_required' 事件。",
            "\n请检查后端（game_controller.py 和 game_routes.py）中所有调用 resolve_attack 的地方，",
            "确保在 'reroll_choice_required' 返回时，已将 'reroll_required' 事件添加到 visual_events 列表中。",
            "\nVisual Events 内容:", gameState.visualEvents
        );
    }

    // --- 绑定所有 UI 事件 ---

    // 阶段 1: 时机
    document.getElementById('timing-近战')?.addEventListener('click', () => selectTiming('近战'));
    document.getElementById('timing-射击')?.addEventListener('click', () => selectTiming('射击'));
    document.getElementById('timing-移动')?.addEventListener('click', () => selectTiming('移动'));
    document.getElementById('timing-抛射')?.addEventListener('click', () => selectTiming('抛射'));
    document.getElementById('timing-快速')?.addEventListener('click', () => selectTiming('快速'));
    document.getElementById('confirm-timing-btn')?.addEventListener('click', confirmTiming);

    // 阶段 2: 姿态
    document.getElementById('stance-defense')?.addEventListener('click', () => changeStance('defense'));
    document.getElementById('stance-agile')?.addEventListener('click', () => changeStance('agile'));
    document.getElementById('stance-attack')?.addEventListener('click', () => changeStance('attack'));
    document.getElementById('confirm-stance-btn')?.addEventListener('click', confirmStance);

    // 阶段 3: 调整
    document.getElementById('action-adjust-move')?.addEventListener('click', () => selectAction('调整移动', 0, 'TP', '', 'system'));
    document.getElementById('action-change-orientation')?.addEventListener('click', () => selectAction('仅转向', 0, 'TP', '', 'system'));
    document.getElementById('skip-adjustment-btn')?.addEventListener('click', skipAdjustment);

    // 阶段 4: 主要动作 (动态绑定)
    document.querySelectorAll('#phase-main-controls .action-item').forEach(item => {
        const actionName = item.dataset.actionName;
        if (actionName) { // 确保它是一个合法的动作项
            const actionRange = item.dataset.actionRange;
            const actionType = item.dataset.actionType;
            const actionCost = item.dataset.actionCost;
            const partSlot = item.dataset.partSlot;
            const isJettison = item.dataset.isJettison === 'true';

            item.addEventListener('click', () => {
                if (item.classList.contains('disabled')) return;

                if (isJettison) {
                    initiateJettison(partSlot);
                } else {
                    selectAction(actionName, parseInt(actionRange, 10), actionType, actionCost, partSlot);
                }
            });
        }
    });

    // 结束回合
    document.getElementById('end-turn-btn')?.addEventListener('click', () => {
        if (!document.getElementById('end-turn-btn').classList.contains('disabled')) {
            document.getElementById('end-turn-form').submit();
        }
    });

    // 弹窗
    document.getElementById('part-selector-cancel-btn')?.addEventListener('click', closePartSelector);
    document.getElementById('dice-roll-close')?.addEventListener('click', closeDiceRollModal);
    document.getElementById('dice-roll-skip')?.addEventListener('click', () => confirmReroll(true));
    document.getElementById('dice-roll-confirm')?.addEventListener('click', () => confirmReroll(false));

    // [MODIFIED] 为重投骰子添加事件委托
    const attackerDiceGroup = document.getElementById('dice-roll-attacker-result');
    const defenderDiceGroup = document.getElementById('dice-roll-defender-result');

    const handleDieClick = (event) => {
        // 查找被点击的 .dice-reroll-group
        const dieElement = event.target.closest('.dice-reroll-group');

        if (dieElement && dieElement.dataset.clickable === "true") {
            // 调用我们模块内的函数
            toggleRerollDie(dieElement);
        }
    };

    attackerDiceGroup?.addEventListener('click', handleDieClick);
    defenderDiceGroup?.addEventListener('click', handleDieClick);


    // 部件详情
    document.getElementById('part-detail-modal-backdrop')?.addEventListener('click', closePartDetailModal);
    document.getElementById('part-detail-close-btn')?.addEventListener('click', closePartDetailModal);
    document.getElementById('part-detail-modal')?.addEventListener('click', (e) => e.stopPropagation());
    document.querySelectorAll('tr[data-part-slot]').forEach(row => {
        row.addEventListener('click', () => {
            showPartDetail(row.dataset.controller, row.dataset.partSlot);
        });
    });

    // 方向选择器
    document.getElementById('orientation-N')?.addEventListener('click', () => setFinalOrientation('N'));
    document.getElementById('orientation-E')?.addEventListener('click', () => setFinalOrientation('E'));
    document.getElementById('orientation-S')?.addEventListener('click', () => setFinalOrientation('S'));
    document.getElementById('orientation-W')?.addEventListener('click', () => setFinalOrientation('W'));
});
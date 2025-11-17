// --- 1. 状态初始化 ---

// 从 HTML 中的 "data island" 脚本标签读取由 Jinja 注入的 JSON 数据
const gameDataElement = document.getElementById('game-data');
const data = JSON.parse(gameDataElement.textContent);

// 模块内的"全局"状态变量
let selectedAction = {}; // 存储玩家当前选择的动作
const CELL_SIZE_PX = 51; // 棋盘格的像素尺寸 (50px + 1px 间隙)
let diceModalTimer = null; // 骰子弹窗的自动关闭计时器

// 从 data 对象解构所有动态数据
const allEntities = data.allEntities; // 游戏中所有实体的列表
const playerID = data.playerID; // 玩家机甲的ID (例如 'player_1')
const playerEntity = data.playerEntity; // 玩家机甲的完整数据对象
const aiEntity = data.aiEntity; // 默认AI机甲的数据对象
const orientationMap = data.orientationMap; // 方向映射 ( 'N': '↑' )
const apiUrls = data.apiUrls; // 所有后端 API 的 URL
const playerLoadout = data.playerLoadout; // 玩家的装备配置 (用于分析)
const aiOpponentName = data.aiOpponentName; // 对手AI的名称 (用于分析)

// 这是我们将引用的主要前端状态机，用于管理UI
const gameState = {
    turnPhase: playerEntity ? playerEntity.turn_phase : 'timing',
    timing: playerEntity ? playerEntity.timing : null,
    openingMoveTaken: playerEntity ? playerEntity.opening_move_taken : false,
    isPlayerLocked: data.isPlayerLocked,
    gameOver: data.gameOver,
    // [核心修复] 检查 'pending_combat' 属性和 'stage' 来确定中断状态
    pendingEffect: playerEntity && playerEntity.pending_combat && playerEntity.pending_combat.stage && playerEntity.pending_combat.stage.includes('EFFECT') ? true : false,
    pendingReroll: playerEntity && playerEntity.pending_combat && playerEntity.pending_combat.stage && playerEntity.pending_combat.stage.includes('REROLL') ? true : false,
    visualEvents: data.visualEvents, // 从后端传递的视觉事件 (如掷骰)
    runProjectilePhase: data.runProjectilePhase, // 是否在加载后自动运行抛射物阶段
    gameMode: data.gameMode,
    defeatCount: data.defeatCount
};

// 静态常量，用于UI显示
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
let tabBtnActions, tabBtnStatus, tabPanelActions, tabPanelStatus;

// --- 2. 核心函数 ---

/**
 * 显示一个包含错误信息并停止自动重载的弹窗。
 * @param {string} title - 弹窗的标题.
 * @param {string} message - 要显示的错误信息.
 */
function showErrorModal(title, message) {
    const backdrop = document.getElementById('error-modal-backdrop');
    const titleEl = document.getElementById('error-title');
    const messageEl = document.getElementById('error-message');

    if (backdrop && titleEl && messageEl) {
        titleEl.innerText = title || '发生未知错误';
        messageEl.innerText = message || '请检查控制台并刷新页面。';
        backdrop.style.display = 'flex';
    } else {
        // 作为最终的后备，如果弹窗HTML不存在，则使用 alert
        console.error("CRITICAL: Error modal HTML elements not found.");
        alert(`发生严重错误:\nTitle: ${title}\nMessage: ${message}\n自动重载已停止。`);
    }
    // 冻结游戏UI，防止进一步操作
    document.querySelectorAll('.action-item, .btn, .selector-group button').forEach(el => {
        if (!el.closest('#error-modal')) {
            el.disabled = true;
        }
    });
}

/**
 * 初始化棋盘上所有实体的视觉位置和朝向。
 * 处理新加载和移动动画。
 */
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

            // 确定朝向和可能的水平翻转 (AI 默认朝左)
            const defaultScaleX = (entityData.controller === 'ai') ? -1 : 1;
            let desiredScaleX = defaultScaleX;
            let desiredRotation = 0;
            const orientation = entityData.orientation;

            if (orientation === 'W') {
                desiredScaleX = -1; // 朝西
            } else if (orientation === 'E') {
                desiredScaleX = 1; // 朝东
            } else if (orientation === 'N') {
                desiredScaleX = defaultScaleX;
                desiredRotation = -90; // 朝北
            } else if (orientation === 'S') {
                desiredScaleX = defaultScaleX;
                desiredRotation = 90; // 朝南
            }

            const finalTransform = `scaleX(${desiredScaleX}) rotate(${desiredRotation}deg)`;
            const finalLeft = `${(currentPos[0] - 1) * CELL_SIZE_PX}px`;
            const finalTop = `${(currentPos[1] - 1) * CELL_SIZE_PX}px`;

            // 如果 'lastPos' 存在且不同，说明实体发生了移动
            if (lastPos && (lastPos[0] !== currentPos[0] || lastPos[1] !== currentPos[1])) {
                // 1. 立即设置朝向
                wrapper.style.transition = 'none';
                img.style.transition = 'transform 0.3s ease';
                img.style.transform = finalTransform;
                // 2. 将实体瞬移到起始位置
                wrapper.style.left = `${(lastPos[0] - 1) * CELL_SIZE_PX}px`;
                wrapper.style.top = `${(lastPos[1] - 1) * CELL_SIZE_PX}px`;

                wrapper.offsetHeight; // 强制浏览器重绘

                // 3. 添加 CSS 过渡并移动到最终位置
                if (entityData.entity_type === 'projectile') {
                    wrapper.style.transition = 'left 0.8s linear, top 0.8s linear'; // 抛射物直线移动
                } else {
                    wrapper.style.transition = 'left 0.4s ease-out, top 0.4s ease-out'; // 机甲正常移动
                }
                wrapper.style.left = finalLeft;
                wrapper.style.top = finalTop;
            } else {
                // 如果没有移动，直接设置最终位置和朝向
                wrapper.style.transition = 'none';
                img.style.transition = 'none';
                wrapper.style.left = finalLeft;
                wrapper.style.top = finalTop;
                img.style.transform = finalTransform;

                // 强制重绘
                wrapper.offsetHeight;

                // 为未来的移动添加过渡
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

/**
 * 在指定坐标显示伤害/未命中/爆炸效果。
 * @param {Array<number>} pos - [x, y] 坐标
 * @param {string} text - 结果类型: '击穿', '无效', 'effect_choice_required'
 */
function showAttackEffect(pos, text) {
    const [x, y] = pos;
    const cell = document.getElementById(`cell-${x}-${y}`);
    if (!cell) return;

    // 如果是击穿或需要选择效果，显示爆炸动画
    if (text === '击穿' || text === 'effect_choice_required') {
        const explosion = document.createElement('div');
        explosion.className = 'explosion-effect';
        cell.appendChild(explosion);
        setTimeout(() => { if (explosion.parentNode) { explosion.parentNode.removeChild(explosion); } }, 800);
    }

    // 显示伤害/未命中数字
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

/**
 * 根据游戏结果显示游戏结束弹窗。
 * @param {string} status - 游戏结果: 'player_win', 'ai_win', 'ai_defeated_in_range'
 */
function showGameOverModal(status) {
    // 记录游戏结果到 Firebase Analytics
    if (window.recordGameOutcome) {
        window.recordGameOutcome(status, playerLoadout, aiOpponentName);
    }

    let modal;
    if (status === 'ai_defeated_in_range') {
        // 靶场模式
        modal = document.getElementById('range-continue-modal');
    } else {
        // 决斗或生存模式
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
    // 禁用所有UI元素
    document.querySelectorAll('.action-item, .btn, .selector-group button').forEach(el => {
        if (!el.closest('#game-over-modal') && !el.closest('#range-continue-modal')) {
            el.disabled = true;
        }
    });
}

/**
 * 根据当前的 gameState.turnPhase 更新左侧边栏的UI (显示/隐藏/禁用按钮)。
 */
function updateUIForPhase() {
    if (gameState.gameOver || !playerEntity || !playerEntity.turn_phase) return;

    // 检查是否需要强制切换回“动作”标签页
    const currentPhase = gameState.turnPhase;
    if (currentPhase === 'timing' || currentPhase === 'stance' ||
        currentPhase === 'adjustment' || currentPhase === 'main') {

        if (tabBtnActions && !tabBtnActions.classList.contains('active')) {
            // 如果玩家在“状态”标签页，但回合阶段推进了，自动切回“动作”标签页
            tabBtnActions.click();
        }
    }

    // 如果玩家机甲宕机，隐藏所有动作UI
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

    // 切换回合阶段控制面板的可见性
    ['timing', 'stance', 'adjustment', 'main'].forEach(phase => {
        const el = document.getElementById(`phase-${phase}-controls`);
        if (el) el.style.display = gameState.turnPhase === phase ? 'block' : 'none';
    });

    // 高亮显示当前选择的时机
    if (gameState.turnPhase === 'timing') {
        document.querySelectorAll('#phase-timing-controls button').forEach(btn => {
            btn.classList.toggle('active', btn.textContent === gameState.timing);
        });
    }
    // 高亮显示当前选择的姿态
    if (gameState.turnPhase === 'stance') {
        document.querySelectorAll('#phase-stance-controls button').forEach(btn => {
            btn.classList.toggle('active', btn.id.includes(playerEntity.stance));
        });
    }

    // 检查是否有中断 (重投或效果选择)
    const message = gameState.pendingReroll ? '请先解决重投！' : '请先选择效果！';
    const isInterrupted = gameState.pendingEffect || gameState.pendingReroll;

    // 禁用所有动作按钮
    document.querySelectorAll('#phase-main-controls .action-item, #phase-adjustment-controls .action-item').forEach(item => {
        if (isInterrupted) {
            item.classList.add('disabled');
            item.title = message;
            return; // 立即禁用并返回
        }

        let isDisabled = false;
        let title = '';
        const baseTitle = item.getAttribute('title') || ''; // 保留 '已使用' 或 '弹药耗尽'

        if (baseTitle === '本回合已使用') {
            isDisabled = true; title = '本回合已使用';
        } else if (baseTitle === '弹药耗尽') {
            isDisabled = true; title = '弹药耗尽';
        } else if (gameState.turnPhase === 'main') {
            // 检查起手动作是否匹配
            if (!gameState.openingMoveTaken && item.dataset.actionType !== gameState.timing) {
                isDisabled = true; title = '非当前时机的起手动作';
            }
            // 检查是否被近战锁定
            if (gameState.isPlayerLocked && item.dataset.actionType === '射击') {
                isDisabled = true; title = '被近战锁定，无法射击';
            }
        }

        item.classList.toggle('disabled', isDisabled);
        item.title = title;
    });

    // 单独处理“结束回合”按钮
    const endTurnBtn = document.getElementById('end-turn-btn');
    if (endTurnBtn) {
        if (isInterrupted) {
            endTurnBtn.classList.add('disabled');
            endTurnBtn.title = message;
        } else {
            // 只有在没有中断时才启用
            endTurnBtn.classList.remove('disabled');
            endTurnBtn.title = '';
        }
    }
}

/**
 * 清除棋盘上所有的高亮和点击事件。
 */
function clearHighlights() {
    document.querySelectorAll('.grid-cell').forEach(c => {
        c.classList.remove('highlight-move', 'highlight-attack', 'highlight-launch');
        c.onclick = null;
    });
    // 重置并隐藏方向选择器
    const orientationSelector = document.getElementById('orientation-selector');
    if (orientationSelector.parentElement !== document.body) {
         document.body.appendChild(orientationSelector);
    }
    orientationSelector.style.display = 'none';
}

/**
 * 玩家点击一个动作时调用 (例如 奔跑, 点射)。
 * @param {string} name - 动作名称
 * @param {number} range - 动作射程
 * @param {string} type - 动作类型 ( '移动', '射击' 等)
 * @param {string} cost - 动作成本 ('S', 'M', 'L')
 * @param {string} partSlot - 部件槽位
 */
function selectAction(name, range, type, cost, partSlot) {
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    clearHighlights();
    selectedAction = { name, range, type, cost, slot: partSlot, player_id: playerID };

    let url = '', body = { action_name: name, part_slot: partSlot, player_id: playerID };

    // 根据动作类型选择正确的 API URL
    if (type === '移动' || name === '调整移动') {
        url = apiUrls.getMoveRange;
    } else if (type === '近战' || type === '射击' || type === '抛射' || type === '快速') {
        url = apiUrls.getAttackRange;
    } else if (name === '仅转向') {
        showOrientationSelector(playerEntity.pos[0], playerEntity.pos[1], true);
        return;
    }

    // 向后端请求有效范围
    if(url) {
        fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })
        .then(res => res.json())
        .then(data => {
            // 高亮移动格
            if(data.valid_moves) data.valid_moves.forEach(([x,y]) => {
                const c = document.getElementById(`cell-${x}-${y}`);
                if (c) {
                    c.classList.add('highlight-move');
                    c.onclick = () => showOrientationSelector(x,y);
                }
            });
            // 高亮攻击目标
            if(data.valid_targets) data.valid_targets.forEach(t => {
                const [x,y] = t.pos;
                const c = document.getElementById(`cell-${x}-${y}`);
                if (c) {
                    c.classList.add('highlight-attack');
                    c.onclick = () => initiateAttack(t.entity_id, x, y, t.is_back_attack);
                }
            });
            // 高亮抛射目标格
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

/**
 * 玩家点击【弃置】动作时调用。
 * @param {string} partSlot - 要弃置的部件槽位
 */
function initiateJettison(partSlot) {
    if (gameState.pendingEffect || gameState.pendingReroll) return;
    clearHighlights();
    postAndReload(apiUrls.jettisonPart, {
        action_name: '【弃置】',
        part_slot: partSlot
    });
}

/**
 * 玩家点击一个高亮的敌方单位时调用。
 * @param {string} entityId - 目标实体ID
 * @param {number} x - 目标 x 坐标
 * @param {number} y - 目标 y 坐标
 * @param {boolean} isBackAttack - 是否为背击
 */
function initiateAttack(entityId, x, y, isBackAttack) {
    selectedAction.targetEntityId = entityId;
    selectedAction.targetPos = [x, y];
    executeAttack();
}

/**
 * 玩家点击一个高亮的抛射目标格时调用。
 * @param {number} x - 目标 x 坐标
 * @param {number} y - 目标 y 坐标
 */
function initiateLaunch(x, y) {
    selectedAction.targetEntityId = null;
    selectedAction.targetPos = [x, y];
    executeAttack();
}

/**
 * 显示“选择攻击部位”弹窗 (用于背击、狙击等)。
 */
function showPartSelector() {
    const modal = document.getElementById('part-selector-modal');
    const buttons = document.getElementById('part-buttons');
    buttons.innerHTML = '';

    // 从 selectedAction 中获取当前目标 ID
    const defenderId = selectedAction.targetEntityId;
    if (!defenderId) {
        console.error("showPartSelector: selectedAction.targetEntityId is not set!");
        return;
    }

    // 从 allEntities 列表中查找正确的目标实体
    const defender = allEntities.find(e => e.id === defenderId);

    if (!defender || !defender.parts) {
         console.error(`showPartSelector: Could not find defender with ID ${defenderId} or it has no parts.`);
         return;
    }

    // 遍历目标的部件并创建按钮
    for (const slot in defender.parts) {
        const part = defender.parts[slot];
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

function closePartSelector() {
    document.getElementById('part-selector-modal').style.display = 'none';
    clearHighlights();
}

/**
 * 玩家在“选择部位”弹窗中点击一个部件时调用。
 * @param {string} partSlot - 选中的部件槽位
 */
function confirmPartSelection(partSlot) {
    selectedAction.targetPartName = partSlot;
    closePartSelector();
    executeAttack(); // 再次调用，这次附带了 targetPartName
}

/**
 * 显示“选择触发效果”弹窗 (用于毁伤/霰射/顺劈)。
 * @param {Array<string>} options - 可选的效果列表, e.g., ['devastating', 'scattershot']
 */
function showEffectSelector(options) {
    const buttonsDiv = document.getElementById('effect-buttons');
    buttonsDiv.innerHTML = '';
    if (!options || options.length === 0) {
        console.error("showEffectSelector 被调用，但没有提供选项！");
        return;
    }
    options.forEach(optionKey => {
        const desc = effectDescriptions[optionKey];
        if (desc) {
            const btn = document.createElement('button');
            btn.className = 'btn';
            btn.style.cssText = desc.style || 'background-color: var(--primary-color);';
            btn.innerHTML = `<strong>${desc.title}</strong><br><small>${desc.text}</small>`;
            btn.onclick = () => confirmEffectChoice(optionKey);
            buttonsDiv.appendChild(btn);
        } else {
            console.warn(`未知的效果键: ${optionKey}`);
        }
    });
    document.getElementById('effect-selector-modal').style.display = 'block';
}

/**
 * 玩家在“选择效果”弹窗中点击一个选项时调用。
 * @param {string} choice - 选中的效果键
 */
function confirmEffectChoice(choice) {
    document.getElementById('effect-selector-modal').style.display = 'none';
    // 发送到后端 API 进行处理
    postAndReload(apiUrls.resolveEffectChoice, { choice: choice, player_id: playerID });
}

/**
 * 在玩家点击移动目标格后，显示方向选择器。
 * @param {number} x - 目标 x 坐标
 * @param {number} y - 目标 y 坐标
 * @param {boolean} isRotationOnly - 这是否是“仅转向”动作
 */
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

/**
 * 玩家在方向选择器上点击一个方向时调用。
 * @param {string} o - 选中的方向 ('N', 'E', 'S', 'W')
 */
function setFinalOrientation(o) {
    selectedAction.finalOrientation = o;
    executeMove();
}

/**
 * [核心API函数] 向后端发送 POST 请求，并期望页面重载或处理中断。
 * 这是所有改变游戏状态的主要途径。
 * @param {string} url - 目标 API URL
 * @param {object} body - 发送到后端的 JSON 数据
 */
function postAndReload(url, body = {}) {
    body.player_id = playerID;
    console.log("Calling postAndReload for:", url, body);

    fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })
    .then(async res => { // 标记为 async 以便读取 .json()
        if (res.redirected) {
            // 如果后端重定向 (例如 /end_turn)，则跟随重定向
            console.log("Response was a redirect, reloading...");
            window.location.href = res.url;
            return null;
        }
        if (!res.ok) {
            // 如果是 HTTP 500 或 404 等错误
            let errorMsg = `HTTP 错误! 状态: ${res.status} ${res.statusText}`;
            try {
                // 尝试解析JSON体以获取更详细的错误
                const errData = await res.json();
                if (errData && errData.message) {
                    errorMsg = errData.message;
                }
            } catch (e) {
                // 响应不是JSON，使用默认的 statusText
            }
            // 抛出这个更详细的错误
            throw new Error(errorMsg);
        }
        return res.json();
    })
    .then(data => {
        if (!data) return; // 如果是重定向，data 为 null

        console.log("Received data:", data);

        if(data.success) {
            // 后端成功处理了请求
            // 检查后端是否要求前端执行特定操作 (中断)

            if (data.action_required === 'select_part') {
                // 中断：需要选择部位
                console.log("Action required: select_part. Showing modal.");
                showPartSelector();
                return; // 停止，不重载
            }

            if (data.action_required === 'select_reroll') {
                // 中断：需要重投
                console.log("Action required: select_reroll. Showing modal.");
                const rerollData = data;
                const attackerIsPlayer = (rerollData.attacker_name.includes("玩家"));
                const defenderIsPlayer = (rerollData.defender_name.includes("玩家"));
                showDiceRollModal(
                    rerollData.dice_details,
                    rerollData.action_name,
                    rerollData.attacker_name,
                    rerollData.defender_name,
                    true, // 可交互
                    attackerIsPlayer,
                    defenderIsPlayer
                );
                return; // 停止，不重载
            }

            if (data.action_required === 'select_effect') {
                // 中断：需要选择效果
                console.log("Action required: select_effect. Showing modal.");
                showEffectSelector(data.options);
                return; // 停止，不重载
            }

            // 默认行为：如果没有中断，则重载页面以显示新状态
            console.log("No action required, reloading.");
            window.location.reload();

        } else {
            // API 调用成功，但业务逻辑失败 (e.g., AP不足, "操作失败")
            console.warn("Operation failed:", data.message);
            // 显示错误弹窗，而不是重载
            showErrorModal('操作失败', data.message || '后端返回了一个错误，但没有提供详情。');
        }
    }).catch(e => {
        // 捕获 fetch 错误 (e.g., HTTP 500, 网络中断)
        console.error("Fetch error:", e.message);
        // 显示错误弹窗，而不是重载
        showErrorModal('后端通信错误', e.message || '一个未知的fetch错误发生了。');
    });
}


// --- 乐观 UI 函数 (用于快速响应) ---
// 这些函数会立即更新UI，然后发送一个“静默”的fetch请求同步到后端。
// 如果请求失败，会强制重载以纠正状态。

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

// --- 其他函数 ---

/**
 * 玩家确认移动或转向后，调用此函数。
 */
function executeMove() {
    let url = selectedAction.isRotationOnly ? apiUrls.changeOrientation : (selectedAction.name === '调整移动' ? apiUrls.executeAdjustMove : apiUrls.movePlayer);
    postAndReload(url, {
        action_name: selectedAction.name,
        target_pos: selectedAction.targetPos,
        final_orientation: selectedAction.finalOrientation,
        part_slot: selectedAction.slot
    });
}

/**
 * 玩家确认攻击目标后，调用此函数。
 */
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

/**
 * 显示部件详情弹窗。
 * @param {string} controller - 'player' 或 'ai'
 * @param {string} slot - 部件槽位 (e.g., 'core', 'left_arm')
 */
function showPartDetail(controller, slot) {
    if (!allEntities) return;

    let entityId = null;
    if (controller === 'player') {
        entityId = playerID;
    } else {
        // 动态查找当前存活的 AI
        const currentAi = allEntities.find(e => e.controller === 'ai' && e.status !== 'destroyed');
        entityId = currentAi ? currentAi.id : null;
    }

    if (!entityId) {
        console.warn(`showPartDetail: 无法确定 ${controller} 的 entityId`);
        return;
    }

    const mech = allEntities.find(e => e.id === entityId);

    if (!mech || !mech.parts || !mech.parts[slot]) {
        console.warn(`Could not find part for ${controller} (ID: ${entityId}) at ${slot}`);
        return;
    }

    const part = mech.parts[slot];
    if (!part) return;

    // 填充弹窗内容
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

    // 根据是否有图片来显示不同内容
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

/**
 * 将 {yellow_count: 1, red_count: 3} 这样的对象转换为 HTML 骰子图标。
 * @param {object} input - 骰子输入对象
 * @returns {string} - HTML 字符串
 */
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

/**
 * 将 {yellow: [['轻击'], ['空白']], red: [['重击']]} 这样的对象转换为 HTML 骰子图标。
 * @param {object} result - 骰子结果对象
 * @param {string} rollType - 'attacker', 'defender', 'secondary'
 * @param {boolean} isClickable - 骰子是否可点击 (用于重投)
 * @returns {string} - HTML 字符串
 */
function formatDiceResult(result, rollType, isClickable = false) {
    let html = '';
    if (!result || Object.keys(result).length === 0) return '<span>无结果</span>';
    const color_order = ['yellow', 'red', 'white', 'blue'];
    let total_dice_groups_rendered = 0;

    for (const color_key of color_order) {
        const dice_groups = result[color_key];
        if (dice_groups && dice_groups.length > 0) {
            // 遍历每一颗骰子
            for (const [die_index, die_results] of dice_groups.entries()) {
                if (total_dice_groups_rendered > 0) {
                     html += `<span style="border-left: 2px solid var(--border-color); margin: 0 0.5rem; height: 1.5rem;"></span>`;
                }
                let dieGroupHtml = '';
                // 遍历一颗骰子上的多个结果 (例如 '轻击*2')
                for (const key of die_results) {
                    const icon = diceIconMap[key] || '?';
                    dieGroupHtml += `<span class="dice-icon dice-result ${key}">${icon}</span>`;
                }

                // 创建可点击的重投组
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

/**
 * 显示掷骰结果弹窗。
 * @param {object} diceDetails - 包含掷骰详情的对象
 * @param {string} actionName - 动作名称
 * @param {string} attackerName - 攻击方名称
 * @param {string} defenderName - 防御方名称
 * @param {boolean} isInteractive - 是否为可交互 (重投) 模式
 * @param {boolean} attackerIsPlayer - 攻击方是否为玩家
 * @param {boolean} defenderIsPlayer - 防御方是否为玩家
 */
function showDiceRollModal(diceDetails, actionName, attackerName, defenderName, isInteractive = false, attackerIsPlayer = false, defenderIsPlayer = false) {
    if (diceModalTimer) {
        clearTimeout(diceModalTimer);
        diceModalTimer = null;
    }

    document.getElementById('dice-roll-title').innerText = `掷骰结算: ${actionName || 'Attack'}`;
    document.getElementById('dice-roll-attacker-name').innerText = attackerName || '攻击方';
    document.getElementById('dice-roll-defender-name').innerText = defenderName || '防御方';

    const details = diceDetails;

    // 填充攻击方骰子
    document.getElementById('dice-roll-attacker-input').innerHTML = formatDiceInput(details.attack_dice_input);
    document.getElementById('dice-roll-attacker-result').innerHTML = formatDiceResult(details.attack_dice_result, 'attacker', isInteractive && attackerIsPlayer);

    // 填充防御方骰子
    document.getElementById('dice-roll-defender-input').innerHTML = formatDiceInput(details.defense_dice_input);
    document.getElementById('dice-roll-defender-result').innerHTML = formatDiceResult(details.defense_dice_result, 'defender', isInteractive && defenderIsPlayer);

    // 填充次要掷骰 (毁伤/霰射/顺劈)
    const secondarySection = document.getElementById('dice-roll-secondary-section');
    if (details.secondary_roll) {
        const secondary = details.secondary_roll;
        let title = "效果结算";
        if (secondary.type === 'devastating_roll') title = "【毁伤】结算";
        if (secondary.type === 'scattershot_roll') title = "【霰射】结算";
        if (secondary.type === 'cleave_roll') title = "【顺劈】结算";
        document.getElementById('dice-roll-secondary-title').innerText = title;
        document.getElementById('dice-roll-secondary-input').innerHTML = formatDiceInput(secondary.defense_dice_input);
        document.getElementById('dice-roll-secondary-result').innerHTML = formatDiceResult(secondary.defense_dice_result, 'secondary', false); // 效果掷骰目前不可重投
        secondarySection.style.display = 'block';
    } else {
        secondarySection.style.display = 'none';
    }

    // 检查玩家是否有链接值来重投
    const playerLinkPoints = (playerEntity && playerEntity.pilot) ? playerEntity.pilot.link_points : 0;
    const canReroll = playerLinkPoints > 0;

    const rerollButtons = document.getElementById('dice-roll-buttons-reroll');
    const closeButton = document.getElementById('dice-roll-buttons-default');
    const confirmButton = document.getElementById('dice-roll-confirm');
    const skipButton = document.getElementById('dice-roll-skip');

    // 根据是否可交互来显示/隐藏按钮
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
        // 非交互模式 (例如 AI 攻击 AI)，自动关闭
        rerollButtons.classList.add('reroll-hidden');
        closeButton.classList.remove('reroll-hidden');
        diceModalTimer = setTimeout(closeDiceRollModal, 5000); // 5秒后自动关闭
    }

    document.getElementById('dice-roll-modal-backdrop').style.display = 'flex';
}

/**
 * 切换一个骰子组的 'selected' 状态 (用于重投)。
 * @param {HTMLElement} element - 被点击的 .dice-reroll-group 元素
 */
function toggleRerollDie(element) {
    if (element.dataset.clickable !== "true") return;
    element.classList.toggle('selected');
}

/**
 * 玩家点击“确认重投”或“跳过”时调用。
 * @param {boolean} isSkipping - 玩家是否点击了“跳过”
 */
function confirmReroll(isSkipping = false) {
    let selections_attacker = [];
    let selections_defender = [];

    if (!isSkipping) {
        // 收集所有被选中的骰子
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
    // 发送重投请求到后端
    postAndReload(apiUrls.resolveReroll, {
        reroll_selections_attacker: selections_attacker,
        reroll_selections_defender: selections_defender
    });
}

/**
 * 关闭掷骰弹窗。
 */
function closeDiceRollModal() {
    if (diceModalTimer) {
        clearTimeout(diceModalTimer);
        diceModalTimer = null;
    }
    document.getElementById('dice-roll-modal-backdrop').style.display = 'none';

    // 这是一个后备，用于显示攻击结果，以防万一
    if (!gameState.pendingReroll) {
        const firstAttackResult = gameState.visualEvents.find(e => e.type === 'attack_result');
        if (firstAttackResult && !gameState.runProjectilePhase) {
            showAttackEffect(firstAttackResult.defender_pos, firstAttackResult.result_text);
        }
    }
}

// --- 3. 初始化和事件绑定 ---

// 当 DOM 加载完成后执行
document.addEventListener('DOMContentLoaded', () => {
    // 初始化
    // 缓存标签页元素
    tabBtnActions = document.getElementById('tab-btn-actions');
    tabBtnStatus = document.getElementById('tab-btn-status');
    tabPanelActions = document.getElementById('tab-panel-actions');
    tabPanelStatus = document.getElementById('tab-panel-status');

    updateUIForPhase(); // 根据当前回合阶段更新UI
    initializeBoardVisuals(); // 设置棋盘上所有单位的初始位置

    // 缓存部件详情弹窗的 DOM 元素
    partDetailModalBackdrop = document.getElementById('part-detail-modal-backdrop');
    partDetailTitle = document.getElementById('part-detail-title');
    partDetailImage = document.getElementById('part-detail-image');
    partDetailStatsContainer = document.getElementById('part-detail-stats-container');
    partDetailStatsList = document.getElementById('part-detail-stats-list');
    partDetailActionsList = document.getElementById('part-detail-actions-list');

    // 检查游戏是否结束
    if (gameState.gameOver) {
        showGameOverModal(gameState.gameOver);
    }

    // 检查待处理效果 (例如 毁伤/霰射/顺劈)
    if (gameState.pendingEffect) {
        const pendingOptions = (playerEntity.pending_combat && playerEntity.pending_combat.options) ? playerEntity.pending_combat.options : [];
        showEffectSelector(pendingOptions);
    }

    // 滚动日志到底部
    const log = document.querySelector('.combat-log');
    if (log) log.scrollTop = log.scrollHeight;

    // 自动运行抛射物阶段 (如果需要)
    if (gameState.runProjectilePhase && !gameState.gameOver && !gameState.pendingEffect && !gameState.pendingReroll) {
        // 禁用UI，显示等待
        document.querySelectorAll('.action-item, .btn, .selector-group button').forEach(el => {
            if (!el.closest('#game-over-modal') && !el.closest('#range-continue-modal') && !el.closest('#error-modal-backdrop')) {
                el.disabled = true;
                el.style.cursor = 'wait';
            }
        });
        // 延迟2秒，让玩家看到AI的移动
        setTimeout(() => {
            fetch(apiUrls.runProjectilePhase, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({})
            })
            .then(res => res.json())
            .then(data => {
                // 收到后端确认后，刷新页面
                if (data && data.success) {
                    window.location.reload();
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

    // 视觉事件处理 (显示掷骰弹窗)
    const rerollEvent = gameState.visualEvents.find(e => e.type === 'reroll_required');
    const diceRollEvent = gameState.visualEvents.find(e => e.type === 'dice_roll');
    const firstAttackResult = gameState.visualEvents.find(e => e.type === 'attack_result');

    if (rerollEvent) {
        // 优先显示重投弹窗
        const rerollData = rerollEvent.details;
        const attackerIsPlayer = (rerollData.attacker_name.includes("玩家"));
        const defenderIsPlayer = (rerollData.defender_name.includes("玩家"));
        showDiceRollModal(
            rerollData.dice_details, rerollData.action_name,
            rerollData.attacker_name, rerollData.defender_name,
            true, attackerIsPlayer, defenderIsPlayer // true = 可交互
        );
    } else if (diceRollEvent) {
        // 其次显示普通掷骰弹窗
        const eventData = diceRollEvent;
        showDiceRollModal(
            eventData.details, eventData.action_name,
            eventData.attacker_name, eventData.defender_name,
            false // false = 不可交互
        );
    } else if (firstAttackResult) {
        // 最后，如果都没有，显示攻击结果 (例如 '击穿')
        showAttackEffect(firstAttackResult.defender_pos, firstAttackResult.result_text);
    }

    // 调试日志：帮助诊断竞态条件
    if (gameState.pendingReroll && !rerollEvent) {
        console.error(
            "--- [状态不一致错误] ---",
            "\n游戏可能已卡死！",
            "\n原因: gameState.pendingReroll 为 true (应显示红色警告条)，",
            "但是 gameState.visualEvents 中 *没有* 找到 'reroll_required' 事件。",
            "\n这通常发生在后端状态与前端不同步时。",
            "\nVisual Events 内容:", gameState.visualEvents,
            "\nPlayer Entity:", playerEntity
        );
    }

    // --- 绑定所有 UI 事件 ---

    // 绑定标签页按钮
    tabBtnActions.addEventListener('click', () => {
        tabBtnActions.classList.add('active');
        tabBtnStatus.classList.remove('active');
        tabPanelActions.style.display = 'block';
        tabPanelStatus.style.display = 'none';
    });

    tabBtnStatus.addEventListener('click', () => {
        tabBtnStatus.classList.add('active');
        tabBtnActions.classList.remove('active');
        tabPanelStatus.style.display = 'block';
        tabPanelActions.style.display = 'none';
    });

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

    // 为重投骰子添加事件委托
    const attackerDiceGroup = document.getElementById('dice-roll-attacker-result');
    const defenderDiceGroup = document.getElementById('dice-roll-defender-result');

    const handleDieClick = (event) => {
        const dieElement = event.target.closest('.dice-reroll-group');
        if (dieElement && dieElement.dataset.clickable === "true") {
            toggleRerollDie(dieElement);
        }
    };

    attackerDiceGroup?.addEventListener('click', handleDieClick);
    defenderDiceGroup?.addEventListener('click', handleDieClick);

    // 部件详情
    document.getElementById('part-detail-modal-backdrop')?.addEventListener('click', closePartDetailModal);
    document.getElementById('part-detail-close-btn')?.addEventListener('click', closePartDetailModal);
    document.getElementById('part-detail-modal')?.addEventListener('click', (e) => e.stopPropagation());

    // 为“状态”标签页中的玩家部件行添加点击事件
    document.querySelectorAll('#tab-panel-status tr[data-part-slot]').forEach(row => {
        row.addEventListener('click', () => {
            showPartDetail(row.dataset.controller, row.dataset.partSlot);
        });
    });
    // 也为 AI 侧边栏的部件行添加点击事件
    document.querySelectorAll('.sidebar table tr[data-part-slot][data-controller="ai"]').forEach(row => {
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
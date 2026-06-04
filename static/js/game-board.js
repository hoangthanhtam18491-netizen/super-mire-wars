// game-board.js — 棋盘渲染、视觉特效、部件UI
// 通过 window.SMW 命名空间与 game.js / game-combat.js 共享状态

(function() {
    const S = window.SMW;

    function initializeBoardVisuals() {
        if (!S.allEntities) return;
        const wrappers = document.querySelectorAll('.mech-icon-wrapper');
        wrappers.forEach(wrapper => {
            try {
                const entityId = wrapper.id.replace('entity-', '').replace('-wrapper', '');
                const entityData = S.allEntities.find(e => e.id === entityId);
                if (!entityData) return;

                const img = document.getElementById(`img-${entityId}`);
                if (!img) return;

                const lastPos = entityData.last_pos || null;
                const currentPos = entityData.pos;
                wrapper.dataset.lastPos = JSON.stringify(lastPos);
                wrapper.dataset.currentPos = JSON.stringify(currentPos);

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
                const finalLeft = `${(currentPos[0] - 1) * S.CELL_SIZE_PX}px`;
                const finalTop = `${(currentPos[1] - 1) * S.CELL_SIZE_PX}px`;

                if (lastPos && (lastPos[0] !== currentPos[0] || lastPos[1] !== currentPos[1])) {
                    wrapper.style.transition = 'none';
                    img.style.transition = 'transform 0.3s ease';
                    img.style.transform = finalTransform;
                    wrapper.style.left = `${(lastPos[0] - 1) * S.CELL_SIZE_PX}px`;
                    wrapper.style.top = `${(lastPos[1] - 1) * S.CELL_SIZE_PX}px`;

                    wrapper.offsetHeight;

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

        // 无人机同格堆叠偏移
        applyDroneStacking();
    }

    function applyDroneStacking() {
        var dronesByTile = {};
        document.querySelectorAll('.mech-icon-wrapper').forEach(function(wrapper) {
            var idMatch = wrapper.id.match(/^entity-(.+)-wrapper$/);
            if (!idMatch) return;
            var eid = idMatch[1];
            var entity = null;
            if (S.allEntities) {
                for (var i = 0; i < S.allEntities.length; i++) {
                    if (S.allEntities[i].id === eid) { entity = S.allEntities[i]; break; }
                }
            }
            if (entity && entity.entity_type === 'drone') {
                var key = entity.pos[0] + ',' + entity.pos[1];
                if (!dronesByTile[key]) dronesByTile[key] = [];
                dronesByTile[key].push(wrapper);
            }
        });
        Object.keys(dronesByTile).forEach(function(key) {
            var wrappers = dronesByTile[key];
            if (wrappers.length > 1) {
                wrappers.forEach(function(w, i) {
                    var offsets = [[-12,-12],[12,-12],[-12,12],[12,12]];
                    var off = offsets[i] || [0,0];
                    w.style.transform = 'translate(' + off[0] + 'px, ' + off[1] + 'px)';
                });
            }
        });
    }
    S.applyDroneStacking = applyDroneStacking;

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

    function updateUIForPhase() {
        if (S.gameState.gameOver || !S.playerEntity || !S.playerEntity.turn_phase) return;

        const currentPhase = S.gameState.turnPhase;
        if (currentPhase === 'timing' || currentPhase === 'stance' ||
            currentPhase === 'adjustment' || currentPhase === 'main') {

            const tabBtnActions = document.getElementById('tab-btn-actions');
            if (tabBtnActions && !tabBtnActions.classList.contains('active')) {
                tabBtnActions.click();
            }
        }

        if (S.playerEntity.stance === 'downed') {
            ['timing', 'stance', 'adjustment', 'main'].forEach(phase => {
                const el = document.getElementById(`phase-${phase}-controls`);
                if (el) el.style.display = 'none';
            });
            const endTurnBtn = document.getElementById('end-turn-btn');
            if(endTurnBtn) {
                endTurnBtn.classList.remove('disabled');
                endTurnBtn.title = '机甲宕机，跳过回合';
            }
            const mobileEndBtn = document.getElementById('mobile-end-turn-btn');
            if(mobileEndBtn) {
                mobileEndBtn.classList.remove('disabled');
                mobileEndBtn.title = '机甲宕机，跳过回合';
            }
            return;
        }

        ['timing', 'stance', 'adjustment', 'main'].forEach(phase => {
            const el = document.getElementById(`phase-${phase}-controls`);
            if (el) el.style.display = S.gameState.turnPhase === phase ? 'block' : 'none';
        });

        if (S.gameState.turnPhase === 'timing') {
            document.querySelectorAll('#phase-timing-controls button').forEach(btn => {
                btn.classList.toggle('active', btn.textContent === S.gameState.timing);
            });
        }
        if (S.gameState.turnPhase === 'stance') {
            document.querySelectorAll('#phase-stance-controls button').forEach(btn => {
                btn.classList.toggle('active', btn.id.includes(S.playerEntity.stance));
            });
        }

        const message = S.gameState.pendingReroll ? '请先解决重投！' : '请先选择效果！';
        const isInterrupted = S.gameState.pendingEffect || S.gameState.pendingReroll;

        document.querySelectorAll('#phase-main-controls .action-item, #phase-adjustment-controls .action-item').forEach(item => {
            if (item.id === 'debug-skill-btn') return;

            if (isInterrupted) {
                item.classList.add('disabled');
                item.title = message;
                return;
            }

            let isDisabled = false;
            let title = '';
            const baseTitle = item.getAttribute('title') || '';

            if (baseTitle === '本回合已使用') {
                isDisabled = true; title = '本回合已使用';
            } else if (baseTitle === '弹药耗尽') {
                isDisabled = true; title = '弹药耗尽';
            } else if (S.gameState.turnPhase === 'main') {
                if (!S.gameState.openingMoveTaken && item.dataset.actionType !== S.gameState.timing) {
                    isDisabled = true; title = '非当前时机的起手动作';
                }
                if (S.gameState.isPlayerLocked && item.dataset.actionType === '射击' && item.dataset.meleeShooting !== 'true') {
                    isDisabled = true; title = '被近战锁定，无法射击';
                }
            }

            item.classList.toggle('disabled', isDisabled);
            item.title = title;
        });

        const debugBtn = document.getElementById('debug-skill-btn');
        if (debugBtn) {
            const debugUsed = (S.playerEntity.actions_used_this_turn || []).some(
                item => item[0] === 'skill' && item[1] === '【除虫】'
            );
            const showDebug = S.gameState.turnPhase === 'main'
                && S.playerEntity.stance === 'attack'
                && S.playerEntity.pilot
                && S.playerEntity.pilot.link_points > 0
                && !isInterrupted
                && !debugUsed;
            debugBtn.style.display = showDebug ? '' : 'none';
            if (debugUsed) {
                debugBtn.title = '本回合已使用';
            }
            debugBtn.classList.toggle('disabled', !showDebug);
        }

        const endTurnBtn = document.getElementById('end-turn-btn');
        if (endTurnBtn) {
            if (isInterrupted) {
                endTurnBtn.classList.add('disabled');
                endTurnBtn.title = message;
            } else {
                endTurnBtn.classList.remove('disabled');
                endTurnBtn.title = '';
            }
        }

        const mobileEndTurnBtn = document.getElementById('mobile-end-turn-btn');
        if (mobileEndTurnBtn) {
            mobileEndTurnBtn.classList.toggle('disabled', isInterrupted);
            mobileEndTurnBtn.title = isInterrupted ? message : '';
        }
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

    function showPartSelector() {
        const modal = document.getElementById('part-selector-modal');
        const buttons = document.getElementById('part-buttons');
        buttons.innerHTML = '';

        const defenderId = S.selectedAction.targetEntityId;
        if (!defenderId) {
            console.error("showPartSelector: selectedAction.targetEntityId is not set!");
            return;
        }

        const defender = S.allEntities.find(e => e.id === defenderId);

        if (!defender || !defender.parts) {
            console.error(`showPartSelector: Could not find defender with ID ${defenderId} or it has no parts.`);
            return;
        }

        for (const slot in defender.parts) {
            const part = defender.parts[slot];
            if (part && part.status !== 'destroyed') {
                const btn = document.createElement('button');
                btn.className = 'btn'; btn.style.backgroundColor = 'var(--primary-color)';
                btn.innerText = `${part.name} (${slot})`;
                btn.onclick = () => S.confirmPartSelection(slot);
                buttons.appendChild(btn);
            }
        }
        modal.style.display = 'block';
    }

    function closePartSelector() {
        document.getElementById('part-selector-modal').style.display = 'none';
        clearHighlights();
    }

    function showOrientationSelector(x, y, isRotationOnly = false) {
        const cell = document.getElementById(`cell-${x}-${y}`);
        const s = document.getElementById('orientation-selector');

        const btnSize = Math.max(40, Math.min(44, Math.floor(S.CELL_SIZE_PX * 0.8)));
        const fontSize = Math.max(10, Math.floor(btnSize * 0.5));
        s.querySelectorAll('.orientation-button').forEach(btn => {
            btn.style.width = btnSize + 'px';
            btn.style.height = btnSize + 'px';
            btn.style.fontSize = fontSize + 'px';
        });

        if (cell) {
            cell.appendChild(s);
        } else {
            document.getElementById('game-board').appendChild(s);
        }
        s.style.display = 'flex';
        S.selectedAction.targetPos = [x, y];
        S.selectedAction.isRotationOnly = isRotationOnly;
    }

    function setFinalOrientation(o) {
        S.selectedAction.finalOrientation = o;
        S.executeMove();
    }

    function showPartDetail(controller, slot) {
        if (!S.allEntities) return;

        let entityId = null;
        if (controller === 'player') {
            entityId = S.playerID;
        } else {
            const currentAi = S.allEntities.find(e => e.controller === 'ai' && e.status !== 'destroyed');
            entityId = currentAi ? currentAi.id : null;
        }

        if (!entityId) {
            console.warn(`showPartDetail: 无法确定 ${controller} 的 entityId`);
            return;
        }

        const mech = S.allEntities.find(e => e.id === entityId);

        if (!mech || !mech.parts || !mech.parts[slot]) {
            console.warn(`Could not find part for ${controller} (ID: ${entityId}) at ${slot}`);
            return;
        }

        const part = mech.parts[slot];
        if (!part) return;

        const partDetailTitle = document.getElementById('part-detail-title');
        const partDetailImage = document.getElementById('part-detail-image');
        const partDetailStatsContainer = document.getElementById('part-detail-stats-container');
        const partDetailStatsList = document.getElementById('part-detail-stats-list');
        const partDetailActionsList = document.getElementById('part-detail-actions-list');

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
        document.getElementById('part-detail-modal-backdrop').style.display = 'flex';
    }

    function closePartDetailModal() {
        const backdrop = document.getElementById('part-detail-modal-backdrop');
        if (backdrop) {
            backdrop.style.display = 'none';
        }
    }

    // 暴露到 SMW 供 game.js 和 game-combat.js 调用
    S.initializeBoardVisuals = initializeBoardVisuals;
    S.showAttackEffect = showAttackEffect;
    S.updateUIForPhase = updateUIForPhase;
    S.clearHighlights = clearHighlights;
    S.showPartSelector = showPartSelector;
    S.closePartSelector = closePartSelector;
    S.showOrientationSelector = showOrientationSelector;
    S.setFinalOrientation = setFinalOrientation;
    S.showPartDetail = showPartDetail;
    S.closePartDetailModal = closePartDetailModal;

})();

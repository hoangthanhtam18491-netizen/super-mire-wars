// game-combat.js — 骰子弹窗、效果选择、重投、拼点UI
// 通过 window.SMW 命名空间与 game.js / game-board.js 共享状态

(function() {
    const S = window.SMW;

    function showEffectSelector(options) {
        const buttonsDiv = document.getElementById('effect-buttons');
        buttonsDiv.innerHTML = '';
        if (!options || options.length === 0) {
            console.error("showEffectSelector 被调用，但没有提供选项！");
            return;
        }
        options.forEach(optionKey => {
            const desc = S.effectDescriptions[optionKey];
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

    function confirmEffectChoice(choice) {
        document.getElementById('effect-selector-modal').style.display = 'none';
        S.postAndReload(S.apiUrls.resolveEffectChoice, { choice: choice, player_id: S.playerID });
    }

    function formatDiceInput(input) {
        let html = ''; if (!input) return '<span>无</span>';
        for (const key in input) {
            const color = S.diceColorMap[key]; const count = input[key];
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
                        const icon = S.diceIconMap[key] || '?';
                        dieGroupHtml += `<span class="dice-icon dice-result ${key}">${icon}</span>`;
                    }

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

    function showClashModal(data) {
        let modal = document.getElementById('clash-modal');

        if (!modal) {
            const isMobile = window.innerWidth <= 768;
            const h2Size = isMobile ? '1.5rem' : '3rem';
            const timingSize = isMobile ? '1.2rem' : '2.5rem';
            const timingPad = isMobile ? '0.5rem 1rem' : '1rem 2rem';
            const vsGap = isMobile ? '1rem' : '4rem';
            const vsSize = isMobile ? '1.5rem' : '3rem';
            const resultSize = isMobile ? '1.2rem' : '2rem';
            const h2Margin = isMobile ? '0.5rem' : '2rem';
            const vsMargin = isMobile ? '1rem' : '2rem';

            const modalHtml = `
                <div id="clash-modal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: rgba(0, 0, 0, 0.85); z-index: 1000; justify-content: center; align-items: center; flex-direction: column; padding: 1rem;">
                    <h2 style="font-size: ${h2Size}; color: #fff; margin-bottom: ${h2Margin}; font-family: 'Impact', sans-serif; letter-spacing: 2px; text-shadow: 0 0 10px #4299e1; text-align: center;">SPEED CLASH</h2>
                    <div style="display: flex; justify-content: center; align-items: center; gap: ${vsGap}; margin-bottom: ${vsMargin}; flex-wrap: wrap;">
                        <div style="text-align: center;">
                            <div style="color: #63b3ed; font-size: 1rem; margin-bottom: 0.25rem;">PLAYER</div>
                            <div id="clash-player-timing" style="font-size: ${timingSize}; font-weight: bold; color: white; border: 2px solid #63b3ed; padding: ${timingPad}; border-radius: 8px; background: rgba(49, 130, 206, 0.2);"></div>
                        </div>
                        <div style="font-size: ${vsSize}; font-weight: bold; color: #cbd5e0; font-style: italic;">VS</div>
                        <div style="text-align: center;">
                            <div style="color: #fc8181; font-size: 1rem; margin-bottom: 0.25rem;">ACE AI</div>
                            <div id="clash-ai-timing" style="font-size: ${timingSize}; font-weight: bold; color: white; border: 2px solid #fc8181; padding: ${timingPad}; border-radius: 8px; background: rgba(229, 62, 62, 0.2);"></div>
                        </div>
                    </div>
                    <div id="clash-reason" style="font-size: 0.85rem; color: #a0aec0; margin-bottom: 1.5rem; max-width: 90vw; text-align: center;"></div>
                    <div id="clash-result" style="font-size: ${resultSize}; font-weight: bold; text-transform: uppercase; animation: pulse 1s infinite;"></div>
                </div>
                <style>
                    @keyframes pulse {
                        0% { transform: scale(1); opacity: 1; }
                        50% { transform: scale(1.05); opacity: 0.8; }
                        100% { transform: scale(1); opacity: 1; }
                    }
                </style>
            `;
            document.body.insertAdjacentHTML('beforeend', modalHtml);
            modal = document.getElementById('clash-modal');
        }

        const winnerText = data.winner === 'player' ? 'INITIATIVE WON' : 'INITIATIVE LOST';
        const winnerColor = data.winner === 'player' ? 'color: #48bb78;' : 'color: #f56565;';

        document.getElementById('clash-player-timing').innerText = data.player_timing;
        document.getElementById('clash-ai-timing').innerText = data.ai_timing;
        document.getElementById('clash-reason').innerText = data.reason;

        const resultEl = document.getElementById('clash-result');
        resultEl.innerText = winnerText;
        resultEl.style.cssText = winnerColor;

        modal.style.display = 'flex';

        if (S.clashModalTimer) clearTimeout(S.clashModalTimer);
        S.clashModalTimer = setTimeout(() => {
            modal.style.display = 'none';
        }, 3000);
    }

    function showDiceRollModal(diceDetails, actionName, attackerName, defenderName, isInteractive = false, attackerIsPlayer = false, defenderIsPlayer = false) {
        if (S.diceModalTimer) {
            clearTimeout(S.diceModalTimer);
            S.diceModalTimer = null;
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

        const playerLinkPoints = (S.playerEntity && S.playerEntity.pilot) ? S.playerEntity.pilot.link_points : 0;
        const canReroll = playerLinkPoints > 1;

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
            S.diceModalTimer = setTimeout(closeDiceRollModal, 5000);
        }

        document.getElementById('dice-roll-modal-backdrop').style.display = 'flex';
    }

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
        S.postAndReload(S.apiUrls.resolveReroll, {
            reroll_selections_attacker: selections_attacker,
            reroll_selections_defender: selections_defender
        });
    }

    function closeDiceRollModal() {
        if (S.diceModalTimer) {
            clearTimeout(S.diceModalTimer);
            S.diceModalTimer = null;
        }
        document.getElementById('dice-roll-modal-backdrop').style.display = 'none';

        if (!S.gameState.pendingReroll) {
            const firstAttackResult = S.gameState.visualEvents.find(e => e.type === 'attack_result');
            if (firstAttackResult && !S.gameState.runProjectilePhase) {
                S.showAttackEffect(firstAttackResult.defender_pos, firstAttackResult.result_text);
            }
        }
    }

    // 暴露到 SMW 供 game.js 调用
    S.showEffectSelector = showEffectSelector;
    S.confirmEffectChoice = confirmEffectChoice;
    S.formatDiceInput = formatDiceInput;
    S.formatDiceResult = formatDiceResult;
    S.showClashModal = showClashModal;
    S.showDiceRollModal = showDiceRollModal;
    S.toggleRerollDie = toggleRerollDie;
    S.confirmReroll = confirmReroll;
    S.closeDiceRollModal = closeDiceRollModal;

})();

/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import publicWidget from "@web/legacy/js/public/public_widget";

const PortalHomeCounters = publicWidget.registry.PortalHomeCounters;

if (PortalHomeCounters) {
    patch(PortalHomeCounters.prototype, {
        async _updateCounters(elem) {
            const placeholders = Array.from(
                this.el.querySelectorAll("[data-placeholder_count]")
            );
            const numberRpc = 3;

            if (!placeholders.length) {
                const spinner = this.el.querySelector(".o_portal_doc_spinner");
                if (spinner) {
                    spinner.remove();
                }
                return [];
            }

            const needed = placeholders.map(
                (documentsCounterEl) =>
                    documentsCounterEl.dataset.placeholder_count
            );
            const counterByRpc = Math.ceil(needed.length / numberRpc);
            const countersAlwaysDisplayed = this._getCountersAlwaysDisplayed();
            const chunkCount = Math.min(numberRpc, needed.length);

            const proms = [...Array(chunkCount).keys()].map(async (i) => {
                const requestCounters = needed.slice(
                    i * counterByRpc,
                    (i + 1) * counterByRpc
                );
                if (!requestCounters.length) {
                    return {};
                }

                const documentsCountersData = await this.rpc("/my/counters", {
                    counters: requestCounters,
                });

                Object.keys(documentsCountersData).forEach((counterName) => {
                    const documentsCounterEl = this.el.querySelector(
                        `[data-placeholder_count='${counterName}']`
                    );
                    if (!documentsCounterEl) {
                        return;
                    }

                    documentsCounterEl.textContent =
                        documentsCountersData[counterName];
                    if (
                        documentsCountersData[counterName] !== 0 ||
                        countersAlwaysDisplayed.includes(counterName)
                    ) {
                        const cardEl = documentsCounterEl.closest(
                            ".o_portal_index_card"
                        );
                        if (cardEl) {
                            cardEl.classList.remove("d-none");
                        }
                    }
                });

                return documentsCountersData;
            });

            const results = await Promise.all(proms);
            const spinner = this.el.querySelector(".o_portal_doc_spinner");
            if (spinner) {
                spinner.remove();
            }
            return results;
        },
    });
}

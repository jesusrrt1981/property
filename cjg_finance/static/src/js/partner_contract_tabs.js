/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class PartnerContractTabs extends Component {
    static template = "cjg_finance.PartnerContractTabs";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            credits: [],
            selectedTab: 0,
            selectedSection: "cuotas",
            loading: false,
        });
        this.loadData();
    }

    async loadData() {
        const record = this.props.record;
        if (!record) return;
        this.state.loading = true;
        try {
            const partnerId = record.resId;
            const field = record.data.sale_credit_ids;
            let creditIds = [];
            if (field?.currentIds) {
                creditIds = field.currentIds.filter((id) => typeof id === "number");
            } else if (field?.records) {
                creditIds = field.records.map((r) => r.resId).filter((id) => typeof id === "number");
            }
            if (creditIds.length) {
                const baseCredits = await this.orm.searchRead(
                    "sale.credit",
                    [["id", "in", creditIds]],
                    [
                        "id",
                        "name",
                        "state",
                        "credit_lines_count",
                        "attachment_ids",
                        "partner_id",
                        "product_id",
                        "company_id",
                        "date_contract",
                        "amount_per_rate",
                        "user_id",
                        "manager_id",
                        "motorista_id",
                        "amount_financed",
                        "amount_interest_value",
                        "total_sold",
                        "credit_amount",
                        "credit_Adeudado",
                    ],
                    { order: "name" }
                );
                const enriched = [];
                for (const c of baseCredits) {
                    const lines = await this.orm.searchRead(
                        "sale.credit.line",
                        [["credit_id", "=", c.id]],
                        [
                            "id",
                            "count",
                            "expected_date_payment",
                            "amount_fixed",
                            "amount_residual",
                            "state",
                        ],
                        { order: "count" }
                    );
                    const followups = await this.orm.searchRead(
                        "followup.sale.credit",
                        [["credit_id", "=", c.id]],
                        ["create_date", "action_type", "credit_id", "internal_notes", "user_id", "next_contact_date"],
                        { order: "create_date desc" }
                    );
                    const attachments = await this.orm.searchRead(
                        "sale.credit.attachment",
                        [["credit_id", "=", c.id]],
                        ["id", "file_name_show", "file_attached_name", "description"],
                        { order: "id desc" }
                    );
                    const docsCount = Array.isArray(c.attachment_ids) ? c.attachment_ids.length : 0;
                    const pagosCount = typeof c.payment_counter === "number" ? c.payment_counter : 0;
                    const cuotasCount = typeof c.credit_lines_count === "number" ? c.credit_lines_count : lines.length;
                    const nextPending = lines.find((l) => l.state === "pending") || null;
                    enriched.push({
                        ...c,
                        counts: {
                            pagos: pagosCount,
                            cuotas: cuotasCount,
                            documentos: docsCount,
                        },
                        lines,
                        followups,
                        attachments,
                        nextPending,
                    });
                }
                this.state.credits = enriched;
            } else {
                this.state.credits = [];
            }
        } catch (e) {
            this.notification.add(e.message || "Error cargando datos", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    onTabChange(index) {
        this.state.selectedTab = index;
    }

    onSectionChange(section) {
        this.state.selectedSection = section;
    }
}

export const partnerContractTabsWidget = {
    component: PartnerContractTabs,
};

registry.category("view_widgets").add("partner_contract_tabs", partnerContractTabsWidget);

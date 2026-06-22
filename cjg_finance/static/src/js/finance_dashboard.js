/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

class FinanceDashboard extends Component {
    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({
            credits: {
                total: 0,
                requested: 0,
                approved: 0,
                refused: 0,
                closed: 0,
                financed_sum: 0,
                residual_sum: 0,
            },
            payments: {
                draft: 0,
                validated: 0,
                paid: 0,
                monthly_series: [],
                spark_path: "",
                total_paid_sum: 0,
            },
            overdues: {
                total: 0,
            },
            portfolio: {
                classA: { count: 0, amount: 0 },
                classB: { count: 0, amount: 0 },
                classC: { count: 0, amount: 0 },
            },
            officers: [],
            maintenance: {
                active: 0,
                suspended: 0,
                revenue: 0,
            },
        });

        onWillStart(async () => {
            await this._loadStats();
        });
    }

    async _loadStats() {
        // Credits
        this.state.credits.total = await this.orm.searchCount("sale.credit", []);
        this.state.credits.requested = await this.orm.searchCount("sale.credit", [["state", "=", "requested"]]);
        this.state.credits.approved = await this.orm.searchCount("sale.credit", [["state", "=", "approved"]]);
        this.state.credits.refused = await this.orm.searchCount("sale.credit", [["state", "=", "refuse"]]);
        this.state.credits.closed = await this.orm.searchCount("sale.credit", [["state", "=", "closed"]]);
        try {
            const creditAgg = await this.orm.readGroup(
                "sale.credit",
                [],
                ["amount_financed:sum", "amount_residual:sum"],
                []
            );
            if (creditAgg && creditAgg[0]) {
                this.state.credits.financed_sum = creditAgg[0]["amount_financed_sum"] || 0;
                this.state.credits.residual_sum = creditAgg[0]["amount_residual_sum"] || 0;
            }
        } catch (e) {
            // readGroup not available or fields missing
        }

        // Payments
        this.state.payments.draft = await this.orm.searchCount("sale.credit.payment", [["state", "=", "draft"]]);
        this.state.payments.validated = await this.orm.searchCount("sale.credit.payment", [["state", "=", "validated"]]);
        this.state.payments.paid = await this.orm.searchCount("sale.credit.payment", [["state", "=", "paid"]]);
        try {
            const paidAgg = await this.orm.readGroup(
                "sale.credit.payment",
                [["state", "=", "paid"]],
                ["amount_total:sum"],
                []
            );
            if (paidAgg && paidAgg[0]) {
                this.state.payments.total_paid_sum = paidAgg[0]["amount_total_sum"] || 0;
            }
        } catch (e) { }

        // Monthly series for sparkline
        try {
            const monthly = await this.orm.readGroup(
                "sale.credit.payment",
                [],
                ["amount_total:sum"],
                ["payment_date:month"]
            );
            const series = (monthly || [])
                .sort((a, b) => (a["payment_date:month"] > b["payment_date:month"]) ? 1 : -1)
                .slice(-12)
                .map((row) => row["amount_total_sum"] || 0);
            this.state.payments.monthly_series = series;
            this.state.payments.spark_path = this._buildSparkPath(series, 240, 60);
        } catch (e) {
            this.state.payments.monthly_series = [];
        }
        // No variaciones mensuales

        // Overdues
        this.state.overdues.total = await this.orm.searchCount("credit.overdue", []);

        // Portfolio Classification (A/B/C)
        await this._loadPortfolioClassification();

        // Officer Statistics
        await this._loadOfficerStats();

        // Maintenance Contracts
        await this._loadMaintenanceStats();
    }
    // Eliminado cálculo de variaciones

    async _loadPortfolioClassification() {
        try {
            const classificationData = await this.orm.readGroup(
                "sale.credit",
                [["state", "=", "approved"]],
                ["client_classification", "credit_Adeudado:sum"],
                ["client_classification"]
            );

            this.state.portfolio = {
                classA: { count: 0, amount: 0 },
                classB: { count: 0, amount: 0 },
                classC: { count: 0, amount: 0 },
            };

            classificationData.forEach(item => {
                const cls = item.client_classification || 'C';
                const key = `class${cls}`;
                if (this.state.portfolio[key]) {
                    this.state.portfolio[key] = {
                        count: item.client_classification_count || 0,
                        amount: item.credit_Adeudado_sum || 0
                    };
                }
            });
        } catch (e) {
            this.state.portfolio = {
                classA: { count: 0, amount: 0 },
                classB: { count: 0, amount: 0 },
                classC: { count: 0, amount: 0 },
            };
        }
    }

    async _loadOfficerStats() {
        try {
            const officerData = await this.orm.readGroup(
                "sale.credit",
                [["state", "=", "approved"]],
                ["user_id", "credit_amount:sum", "credit_Adeudado:sum"],
                ["user_id"]
            );

            this.state.officers = officerData.map(item => ({
                name: item.user_id ? item.user_id[1] : "Sin Asignar",
                collected: item.credit_amount_sum || 0,
                pending: item.credit_Adeudado_sum || 0,
                count: item.user_id_count || 0
            })).sort((a, b) => b.collected - a.collected).slice(0, 5);
        } catch (e) {
            this.state.officers = [];
        }
    }

    async _loadMaintenanceStats() {
        try {
            const activeCount = await this.orm.searchCount("maintenance.contract", [["state", "=", "active"]]);
            const suspendedCount = await this.orm.searchCount("maintenance.contract", [["state", "=", "suspended"]]);

            const revenueData = await this.orm.readGroup(
                "maintenance.contract",
                [],
                ["total_paid:sum"],
                []
            );

            this.state.maintenance = {
                active: activeCount,
                suspended: suspendedCount,
                revenue: revenueData && revenueData[0] ? revenueData[0].total_paid_sum || 0 : 0
            };
        } catch (e) {
            this.state.maintenance = { active: 0, suspended: 0, revenue: 0 };
        }
    }

    _buildSparkPath(values, width, height) {
        if (!values || !values.length) return "";
        const max = Math.max(...values);
        const min = Math.min(...values);
        const len = values.length;
        const stepX = width / Math.max(len - 1, 1);
        const normalize = (v) => {
            if (max === min) return height / 2;
            const y = ((v - min) / (max - min)) * (height - 8);
            return height - 4 - y;
        };
        let d = "";
        values.forEach((v, i) => {
            const x = i * stepX;
            const y = normalize(v);
            d += i === 0 ? `M ${x},${y}` : ` L ${x},${y}`;
        });
        return d;
    }

    // Navigation helpers
    viewCredits(state) {
        let domain = [];
        let name = "Créditos";
        if (state && state !== "all") {
            domain = [["state", "=", state]];
            name = `Créditos (${state})`;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "sale.credit",
            view_mode: "tree",
            views: [[false, "tree"], [false, "kanban"], [false, "form"], [false, "graph"]],
            target: "current",
            context: { create: false },
            domain,
        });
    }

    viewPayments(state) {
        let domain = [];
        let name = "Pagos";
        if (state && state !== "all") {
            domain = [["state", "=", state]];
            name = `Pagos (${state})`;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "sale.credit.payment",
            view_mode: "tree",
            views: [[false, "tree"], [false, "form"]],
            target: "current",
            context: { create: false },
            domain,
        });
    }

    viewOverdues() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Moras",
            res_model: "credit.overdue",
            view_mode: "tree",
            views: [[false, "tree"], [false, "form"]],
            target: "current",
            context: { create: false },
            domain: [],
        });
    }

    viewPortfolioByClass(classification) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Cartera Clase ${classification}`,
            res_model: "sale.credit",
            view_mode: "tree",
            views: [[false, "tree"], [false, "form"]],
            target: "current",
            domain: [["client_classification", "=", classification], ["state", "=", "approved"]],
        });
    }

    viewMaintenanceContracts(state) {
        let domain = state ? [["state", "=", state]] : [];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Contratos de Mantenimiento",
            res_model: "maintenance.contract",
            view_mode: "tree",
            views: [[false, "tree"], [false, "form"], [false, "calendar"]],
            target: "current",
            domain,
        });
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('es-DO', {
            style: 'currency',
            currency: 'DOP'
        }).format(amount || 0);
    }
}

FinanceDashboard.template = "cjg_finance.finance_dashboard";
registry.category("actions").add("finance_dashboard", FinanceDashboard);

export default FinanceDashboard;

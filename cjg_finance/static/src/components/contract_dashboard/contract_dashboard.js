/** @odoo-module **/

import { Component, useState, onWillStart, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ContractDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            partner: null,
            contracts: [],
            activeContractId: null,
            activeContract: null,
            activeTab: 'cuotas',  // cuotas | historial | documentos
            stats: {
                pagos: 0,
                cuotas: 0,
                documentos: 0
            },
            payments: [],
            creditLines: [],
            documents: [],
            loading: true,
            chatMessage: '',
            searchTerm: '',
            searchResults: []
        });

        onWillStart(async () => {
            await this.loadData();
        });

        onMounted(() => {
            this.state.loading = false;
        });
    }

    async loadData() {
        const partnerId = this.props.partnerId || this.props.context?.active_id;

        if (!partnerId) {
            // Modo búsqueda de cliente (no hay cliente preseleccionado)
            return;
        }

        try {
            // Cargar información del partner
            const partners = await this.orm.read("res.partner", [partnerId], ["name", "vat", "email", "phone"]);
            this.state.partner = partners[0];

            // Cargar todos los contratos del cliente
            await this.loadPartnerContracts(partnerId);

            // Si hay contratos, seleccionar el primero activo o el primero de la lista
            if (this.state.contracts.length > 0) {
                const activeContract = this.state.contracts.find(c => c.state === 'approved') || this.state.contracts[0];
                await this.selectContract(activeContract.id);
            }
        } catch (error) {
            console.error("Error loading contract dashboard:", error);
            this.notification.add("Error al cargar los contratos", { type: "danger" });
        }
    }

    // Busca automáticamente 1.5s después de dejar de escribir (sin tener que dar
    // Enter). Enter sigue funcionando para búsqueda inmediata.
    onSearchInput(ev) {
        if (ev && ev.target) {
            this.state.searchTerm = ev.target.value;
        }
        if (this._searchDebounce) {
            clearTimeout(this._searchDebounce);
            this._searchDebounce = null;
        }
        const query = (this.state.searchTerm || '').trim();
        if (!query) {
            this.state.searchResults = [];
            return;
        }
        this._searchDebounce = setTimeout(() => {
            this._searchDebounce = null;
            this.searchPartners();
        }, 1500);
    }

    async searchPartners(ev) {
        if (ev && ev.type === 'keydown' && ev.key !== 'Enter') return;
        // Si llega por Enter o clic, cancelar cualquier búsqueda con debounce pendiente.
        if (this._searchDebounce) {
            clearTimeout(this._searchDebounce);
            this._searchDebounce = null;
        }

        const query = (this.state.searchTerm || '').trim();
        if (!query) return;

        this.state.loading = true;
        try {
            // Reutilizar la MISMA búsqueda del Punto de Venta.
            // cjg.pos.session.search_partner_or_contract deduplica el cliente
            // (partner canónico vía commercial_partner_id + identidad por
            // cédula/teléfono) y enriquece con contratos, evitando que el mismo
            // cliente aparezca en varias filas. Así el dashboard muestra UNA
            // sola fila por cliente, exactamente igual que el POS.
            const rawResults = await this.orm.call(
                "cjg.pos.session",
                "search_partner_or_contract",
                [query]
            );

            // El dashboard es centrado en cliente: conservar solo las entradas
            // con partner identificado y mapear al shape que espera la vista.
            const seen = new Set();
            const results = [];
            for (const item of rawResults || []) {
                const partnerId = item.partner_id || item.id;
                if (!partnerId) continue;
                // El Dashboard de Contratos es exclusivo de clientes con
                // CONTRATOS de crédito. Se excluyen planillas, mantenimientos y
                // clientes sin contrato (a diferencia del buscador del POS).
                const hasContract = item.has_credits || (item.credit_count || 0) > 0 || !!item.credit_id;
                if (!hasContract) continue;
                if (seen.has(partnerId)) continue;
                seen.add(partnerId);
                results.push({
                    id: partnerId,
                    name: item.name || '',
                    vat: item.vat || '',
                    email: item.email || '',
                });
            }

            this.state.searchResults = results;
        } catch (error) {
            console.error("Error searching:", error);
            this.notification.add("Error en la búsqueda", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async selectPartnerFromSearch(partner) {
        this.state.partner = partner;
        this.state.searchTerm = '';
        this.state.searchResults = [];
        this.state.loading = true;

        try {
            await this.loadPartnerContracts(partner.id);
            // Si hay contratos, seleccionar el primero activo o el primero de la lista
            if (this.state.contracts.length > 0) {
                const activeContract = this.state.contracts.find(c => c.state === 'approved') || this.state.contracts[0];
                await this.selectContract(activeContract.id);
            }
        } catch (error) {
            console.error("Error loading partner contracts:", error);
            this.notification.add("Error al cargar contratos del cliente", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async loadPartnerContracts(partnerId) {
        // Cargar TODOS los contratos del cliente (sale.credit).
        // Se usa `child_of` en lugar de `=` para abarcar toda la familia
        // comercial del partner: como la búsqueda deduplica al partner
        // canónico (commercial_partner_id), los contratos registrados en
        // contactos hijos seguirían apareciendo. `child_of` es un superconjunto
        // de `=` (incluye al propio partner y sus descendientes), nunca reduce.
        const contracts = await this.orm.searchRead(
            "sale.credit",
            [["partner_id", "child_of", partnerId]],
            [
                "name",
                "legacy_contract_number",
                "state",
                "amount_financed",
                "amount_residual",
                "amount_per_rate",
                "installment_id",
                "payment_count",
                "partner_id",
                "user_id",
                "product_id",
                "company_id",
                "create_date",
                "vat"
            ],
            { order: "create_date desc" }
        );

        this.state.contracts = contracts;
    }

    async selectContract(contractId) {
        this.state.loading = true;
        this.state.activeContractId = contractId;

        try {
            // Cargar detalles completos del contrato
            const contracts = await this.orm.read("sale.credit", [contractId], [
                "name",
                "legacy_contract_number",
                "state",
                "amount_financed",
                "amount_residual",
                "amount_per_rate",
                "installment_id",
                "payment_count",
                "partner_id",
                "user_id",
                "product_id",
                "asesor_id",
                "create_date",
                "vat"
            ]);

            this.state.activeContract = contracts[0];

            // Cargar líneas de crédito (cuotas)
            await this.loadCreditLines(contractId);

            // Cargar pagos
            await this.loadPayments(contractId);

            // Cargar documentos relacionados
            await this.loadDocuments(contractId);

            // Calcular estadísticas
            this.calculateStats();

        } catch (error) {
            console.error("Error selecting contract:", error);
            this.notification.add("Error al cargar el contrato", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async loadCreditLines(contractId) {
        // Cargar las líneas de crédito (cuotas programadas)
        const lines = await this.orm.searchRead(
            "sale.credit.line",
            [["credit_id", "=", contractId]],
            [
                "name",
                "expected_date_payment",
                "amount_capital",
                "amount_interest",
                "amount_paid",
                "amount_residual",
                "state"
            ],
            { order: "expected_date_payment asc" }
        );

        this.state.creditLines = lines;
    }

    async loadPayments(contractId) {
        // Cargar historial de pagos realizados
        const payments = await this.orm.searchRead(
            "sale.credit.payment",
            [["credit_id", "=", contractId]],
            [
                "name",
                "payment_date",
                "amount_total",
                "state"
            ],
            { order: "payment_date desc" }
        );

        this.state.payments = payments;
    }

    async loadDocuments(contractId) {
        // Cargar documentos adjuntos
        const attachments = await this.orm.searchRead(
            "ir.attachment",
            [
                ["res_model", "=", "sale.credit"],
                ["res_id", "=", contractId]
            ],
            ["name", "mimetype", "file_size", "create_date"],
            { order: "create_date desc" }
        );

        this.state.documents = attachments;
    }

    calculateStats() {
        const contract = this.state.activeContract;

        this.state.stats = {
            pagos: contract.payment_count || 0,
            cuotas: contract.installment_id ? contract.installment_id[1] : 0,
            documentos: this.state.documents.length
        };
    }

    getCurrentContract() {
        return this.state.contracts.find(c => c.id === this.state.activeContractId) || {};
    }

    getContractBadgeClass(state) {
        const mapping = {
            'draft': 'badge-draft',
            'requested': 'badge-draft',
            'approved': 'badge-activo',
            'closed': 'badge-saldado',
            'refuse': 'badge-refused',
            'cancelled': 'badge-cancelled'
        };
        return mapping[state] || 'badge-draft';
    }

    getContractBadgeText(state) {
        const mapping = {
            'draft': 'BORRADOR',
            'requested': 'SOLICITADO',
            'approved': 'ACTIVO',
            'closed': 'SALDADO',
            'refuse': 'RECHAZADO',
            'cancelled': 'CANCELADO'
        };
        return mapping[state] || state.toUpperCase();
    }

    changeTab(tabName) {
        this.state.activeTab = tabName;
    }

    async onStatCardClick(statType) {
        // Al hacer clic en una card de stats, cambiar a la tab correspondiente
        const tabMapping = {
            'pagos': 'historial',
            'cuotas': 'cuotas',
            'documentos': 'documentos'
        };

        this.changeTab(tabMapping[statType] || 'cuotas');
    }

    async validateContract() {
        if (!this.state.activeContract) return;

        try {
            await this.orm.call(
                "sale.credit",
                "action_approve",
                [[this.state.activeContractId]]
            );

            this.notification.add("Contrato validado exitosamente", { type: "success" });
            await this.selectContract(this.state.activeContractId);
        } catch (error) {
            console.error("Error validating contract:", error);
            this.notification.add("Error al validar el contrato", { type: "danger" });
        }
    }

    async addPayment() {
        if (!this.state.activeContract) return;

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Nuevo Pago',
            res_model: 'sale.credit.payment',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: {
                default_credit_id: this.state.activeContractId,
                default_partner_id: this.state.activeContract.partner_id[0],
                default_amount_total: this.state.activeContract.amount_per_rate
            }
        });
    }

    async openContract() {
        if (!this.state.activeContract) return;

        this.action.doAction({
            type: 'ir.actions.act_window',
            name: this.state.activeContract.name,
            res_model: 'sale.credit',
            res_id: this.state.activeContractId,
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'current'
        });
    }

    async sendChatMessage(ev) {
        if (ev && ev.type === 'keydown' && ev.key !== 'Enter') return;

        if (!this.state.chatMessage.trim()) return;

        try {
            await this.orm.call(
                "sale.credit",
                "message_post",
                [[this.state.activeContractId]],
                {
                    body: this.state.chatMessage,
                    message_type: 'comment',
                    subtype_xmlid: 'mail.mt_comment'
                }
            );

            this.state.chatMessage = '';
            this.notification.add("Mensaje enviado", { type: "success" });
        } catch (error) {
            console.error("Error sending message:", error);
            this.notification.add("Error al enviar el mensaje", { type: "danger" });
        }
    }

    formatCurrency(value) {
        if (!value && value !== 0) return 'RD$ 0.00';
        return `RD$ ${parseFloat(value).toLocaleString('es-DO', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        })}`;
    }

    formatDate(dateStr) {
        if (!dateStr) return '-';
        const date = new Date(dateStr);
        return date.toLocaleDateString('es-DO', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    }

    getPaymentMethodLabel(method) {
        const labels = {
            'cash': 'Efectivo',
            'bank_deposit': 'Depósito',
            'card': 'Tarjeta',
            'check': 'Cheque',
            'transfer': 'Transferencia',
            'motorizado': 'Motorizado',
            'collection_office': 'Oficina'
        };
        return labels[method] || method;
    }

    getLineStateClass(state) {
        const mapping = {
            'paid': 'success',
            'partial': 'warning',
            'due': '',
            'overdue': 'danger'
        };
        return mapping[state] || '';
    }

    getPaidBadgeClass(isPaid) {
        return isPaid ? 'badge-success' : 'badge-secondary';
    }
}

ContractDashboard.template = "cjg_finance.ContractDashboard";
ContractDashboard.props = {
    partnerId: { type: Number, optional: true },
    context: { type: Object, optional: true },
    action: { type: Object, optional: true },
    actionId: { type: Number, optional: true },
    className: { type: String, optional: true },
    globalState: { type: Object, optional: true }
};

registry.category("actions").add("contract_dashboard", ContractDashboard);

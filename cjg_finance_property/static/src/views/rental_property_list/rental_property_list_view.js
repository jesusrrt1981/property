/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { RentalPropertyDashboard } from '@cjg_finance_property/components/rental_property_dashboard';

export class RentalPropertyDashboardRenderer extends ListRenderer {};

RentalPropertyDashboardRenderer.template = 'cjg_finance_property.RentalPropertyListView';
RentalPropertyDashboardRenderer.components= Object.assign({}, ListRenderer.components, {RentalPropertyDashboard})

export const RentalPropertyDashboardListView = {
    ...listView,
    Renderer: RentalPropertyDashboardRenderer,
};

registry.category("views").add("rental_property_dashboard_list", RentalPropertyDashboardListView);
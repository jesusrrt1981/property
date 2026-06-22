/** @odoo-module **/

import { session } from '@web/session';
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart, onMounted } from "@odoo/owl";

export class RentalPropertyDashboard extends Component {
    setup() {
        this.action = useService('action');
        this.rpc = useService('rpc')
        this.state = useState({
            'property_data': {}
        })
        onMounted(async ()=>{
            const data = await this.rpc('/get/property/data')
            this.state.property_data = data
        })


    }
    viewAllProperties(status){
        let domain, context;
        if (status === 'all') {
           domain = [['stage', '!=', 'draft']]
        } else {
            domain = [['stage', '=', status]]
        }
        context = { 'create': true }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Properties',
            res_model: 'property.details',
            view_mode: 'tree',
            views: [[false, 'tree'], [false, 'kanban'], [false, 'form']],
            target: 'current',
            context: context,
            domain: domain,
        });
    }
    viewProperties(status, type){
        let domain, context;
        if (status === 'all') {
           domain = [['stage', '!=', 'draft'],['type','=',type]]
        } else {
            domain = [['stage', '=', status],['type','=', type]]
        }
        context = { 'create': true }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Properties',
            res_model: 'property.details',
            view_mode: 'tree',
            views: [[false, 'tree'], [false, 'kanban'], [false, 'form']],
            target: 'current',
            context: context,
            domain: domain,
        });
    }
}

RentalPropertyDashboard.template = 'cjg_finance_property.RentalPropertyDashboard';

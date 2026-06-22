/** @odoo-module **/
import { registry } from "@web/core/registry";
import { getDefaultConfig } from "@web/views/view";
import { useService } from "@web/core/utils/hooks";


const { Component, useSubEnv, useState, onMounted, onWillStart, useRef } = owl;

class PropertyDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({
            propertyStats: {
                'total_property': 0,
                'avail_property': 0,
                'sold_property': 0,
                'booked_property': 0,
                'sale_property': 0,
                'sold_total': "0",
                'sale_sold': 0,
                'booked': 0,
                'draft_contract': 0,
                'running_contract': 0,
                'expire_contract': 0,
                'pending_invoice': 0,
                'rent_total': "0",
                'region_count': 0,
                'project_count': 0,
                'subproject_count': 0,
                'customer_count': 0,
                'pending_invoice_sale': 0,
                'close_contract': 0,
                'extend_contract': 0,
                'refund': 0,
            },
            propertyType: { 'x-axis': [], 'y-axis': [] },
        });
        useSubEnv({
            config: {
                ...getDefaultConfig(),
                ...this.env.config,
            },
        });
        this.propertyType = useRef('propertyType');
        this.propertyStages = useRef('propertyStages');
        this.soldTopBroker = useRef('soldTopBroker');
        this.soldDuePaid = useRef('soldDuePaid');
        this.worldMap = useRef('worldMap');
        onWillStart(async () => {
            let propertyData = await this.orm.call('property.details', 'get_property_stats', []);
            if (propertyData) {
                this.state.propertyStats = propertyData;
                this.state.propertyType = { 'x-axis': propertyData['property_type'][0], 'y-axis': propertyData['property_type'][1] }
                this.state.propertyStages = { 'x-axis': propertyData['property_stage'][0], 'y-axis': propertyData['property_stage'][1] }
                this.state.soldTopBroker = { 'x-axis': (propertyData['sold_top_broker'] ? propertyData['sold_top_broker'][0] : []), 'y-axis': (propertyData['sold_top_broker'] ? propertyData['sold_top_broker'][1] : []) }
                this.state.soldDuePaid = { 'x-axis': propertyData['due_paid_amount'][0], 'y-axis': propertyData['due_paid_amount'][1] }
                this.state.propertyMapData = propertyData['property_map_data']
            }
        });
        onMounted(() => {
            this.renderPropertyType(this.propertyType.el, this.state.propertyType);
            // Add small delay to ensure DOM elements are fully rendered
            setTimeout(() => {
                this.renderSoldTopBroker();
                this.renderSoldDuePaid();
            }, 100);
            this.renderMapProperties(this.worldMap.el, this.state.propertyMapData);
        })
    }
    renderPropertyType(div, sessionData) {
        const safeSession = sessionData || { 'x-axis': [], 'y-axis': [] };
        const yData = Array.isArray(safeSession['y-axis']) ? safeSession['y-axis'] : [];
        var root = am5.Root.new(div);
        root.setThemes([
            am5themes_Animated.new(root)
        ]);
        var data = [{
            name: "Propiedad",
            steps: Number(yData[0]) || 0,
            pictureSettings: {
                src: "cjg_finance_property/static/src/img/land-dash.svg"
            }
        },
            //{
        //     name: "Residential",
        //     steps: sessionData['y-axis'][1],
        //     pictureSettings: {
        //         src: "cjg_finance_property/static/src/img/re-dash.svg"
        //     }
        // }, {
        //     name: "Commercial",
        //     steps: sessionData['y-axis'][2],
        //     pictureSettings: {
        //         src: "cjg_finance_property/static/src/img/come-dash.svg"
        //     }
        // }, {
        //     name: "Industrial",
        //     steps: sessionData['y-axis'][3],
        //     pictureSettings: {
        //         src: "cjg_finance_property/static/src/img/ind-dash.svg"
        //     }
        // }
        ];
        var chart = root.container.children.push(
            am5xy.XYChart.new(root, {
                panX: false,
                panY: false,
                wheelX: "none",
                wheelY: "none",
                paddingBottom: 50,
                paddingTop: 40,
                paddingLeft: 0,
                paddingRight: 0
            })
        );
        var xRenderer = am5xy.AxisRendererX.new(root, {
            minorGridEnabled: true,
            minGridDistance: 60
        });
        xRenderer.grid.template.set("visible", false);
        var xAxis = chart.xAxes.push(
            am5xy.CategoryAxis.new(root, {
                paddingTop: 40,
                categoryField: "name",
                renderer: xRenderer
            })
        );
        var yRenderer = am5xy.AxisRendererY.new(root, {});
        yRenderer.grid.template.set("strokeDasharray", [3]);

        var yAxis = chart.yAxes.push(
            am5xy.ValueAxis.new(root, {
                min: 0,
                renderer: yRenderer
            })
        );
        var series = chart.series.push(
            am5xy.ColumnSeries.new(root, {
                name: "Income",
                xAxis: xAxis,
                yAxis: yAxis,
                valueYField: "steps",
                categoryXField: "name",
                sequencedInterpolation: true,
                calculateAggregates: true,
                maskBullets: false,
                tooltip: am5.Tooltip.new(root, {
                    dy: -30,
                    pointerOrientation: "vertical",
                    labelText: "{valueY}"
                })
            })
        );
        series.columns.template.setAll({
            strokeOpacity: 0,
            cornerRadiusBR: 10,
            cornerRadiusTR: 10,
            cornerRadiusBL: 10,
            cornerRadiusTL: 10,
            maxWidth: 50,
            fillOpacity: 0.8
        });
        var currentlyHovered;
        series.columns.template.events.on("pointerover", function (e) {
            handleHover(e.target.dataItem);
        });
        series.columns.template.events.on("pointerout", function (e) {
            handleOut();
        });
        function handleHover(dataItem) {
            if (dataItem && currentlyHovered != dataItem) {
                handleOut();
                currentlyHovered = dataItem;
                var bullet = dataItem.bullets[0];
                bullet.animate({
                    key: "locationY",
                    to: 1,
                    duration: 600,
                    easing: am5.ease.out(am5.ease.cubic)
                });
            }
        }
        function handleOut() {
            if (currentlyHovered) {
                var bullet = currentlyHovered.bullets[0];
                bullet.animate({
                    key: "locationY",
                    to: 0,
                    duration: 600,
                    easing: am5.ease.out(am5.ease.cubic)
                });
            }
        }
        var circleTemplate = am5.Template.new({});
        series.bullets.push(function (root, series, dataItem) {
            var bulletContainer = am5.Container.new(root, {});
            var circle = bulletContainer.children.push(
                am5.Circle.new(
                    root,
                    {
                        radius: 34
                    },
                    circleTemplate
                )
            );
            var maskCircle = bulletContainer.children.push(
                am5.Circle.new(root, { radius: 27 })
            );
            var imageContainer = bulletContainer.children.push(
                am5.Container.new(root, {
                    mask: maskCircle
                })
            );
            var image = imageContainer.children.push(
                am5.Picture.new(root, {
                    templateField: "pictureSettings",
                    centerX: am5.p50,
                    centerY: am5.p50,
                    width: 60,
                    height: 60
                })
            );
            return am5.Bullet.new(root, {
                locationY: 0,
                sprite: bulletContainer
            });
        });
        series.set("heatRules", [
            {
                dataField: "valueY",
                min: am5.color(0xe5dc36),
                max: am5.color(0x5faa46),
                target: series.columns.template,
                key: "fill"
            },
            {
                dataField: "valueY",
                min: am5.color(0xe5dc36),
                max: am5.color(0x5faa46),
                target: circleTemplate,
                key: "fill"
            }
        ]);
        series.data.setAll(data);
        xAxis.data.setAll(data);
        var cursor = chart.set("cursor", am5xy.XYCursor.new(root, {}));
        cursor.lineX.set("visible", false);
        cursor.lineY.set("visible", false);

        cursor.events.on("cursormoved", function () {
            var dataItem = series.get("tooltip").dataItem;
            if (dataItem) {
                handleHover(dataItem);
            } else {
                handleOut();
            }
        });
        series.appear();
        chart.appear(1000, 100);
    }

    renderSoldTopBroker() {
        var options = {
            series: [{
                name: "Sale Contracts",
                data: this.state.soldTopBroker['y-axis']
            }],
            chart: {
                height: 200,
                type: 'bar',
            },
            colors: ['#11D3F3', '#38DEDF', '#5FE8CB', '#86F3B6', '#ADFDA2'],
            plotOptions: {
                bar: {
                    columnWidth: '40%',
                    distributed: true,
                }
            },
            dataLabels: {
                enabled: true
            },
            legend: {
                show: true
            },
            xaxis: {
                categories: this.state.soldTopBroker['x-axis'],
                labels: {
                    style: {
                        colors: ['#11D3F3', '#38DEDF', '#5FE8CB', '#86F3B6', '#ADFDA2'],
                        fontSize: '12px'
                    }
                }
            }
        };
        this.renderGraph(this.soldTopBroker.el, options);
    }

    renderSoldDuePaid() {
        const rawSeries = Array.isArray(this.state.soldDuePaid['y-axis']) ? this.state.soldDuePaid['y-axis'] : [];
        const series = rawSeries.map((v) => Number(v) || 0);
        const labels = Array.isArray(this.state.soldDuePaid['x-axis']) ? this.state.soldDuePaid['x-axis'] : [];
        const options = {
            series: series.length ? series : [0, 0],
            chart: {
                type: 'pie',
                height: 225
            },
            colors: ['#FF884B', '#64E291'],
            dataLabels: {
                enabled: false
            },
            labels: labels.length ? labels : ['Due', 'Paid'],
            legend: {
                position: 'bottom',
            },
        };
        this.renderGraph(this.soldDuePaid.el, options);
    }
    renderMapProperties(div, sessionData) {
        const safeData = Array.isArray(sessionData) ? sessionData : [];
        const root = am5.Root.new(div);
        root.setThemes([am5themes_Animated.new(root)]);
        const chart = root.container.children.push(
            am5map.MapChart.new(root, {
                panX: "rotateX",
                panY: "translateY",
                projection: am5map.geoMercator(),
            })
        );
        chart.set("zoomControl", am5map.ZoomControl.new(root, {}));
        const polygonSeries = chart.series.push(
            am5map.MapPolygonSeries.new(root, {
                geoJSON: am5geodata_worldLow,
                exclude: ["AQ"]
            })
        );
        polygonSeries.mapPolygons.template.setAll({
            fill: am5.color(0xdadada)
        });
        const pointSeries = chart.series.push(am5map.ClusteredPointSeries.new(root, {}));

        pointSeries.set("clusteredBullet", function (root) {
            const container = am5.Container.new(root, {
                cursorOverStyle: "pointer"
            });
            const circle1 = container.children.push(am5.Circle.new(root, {
                radius: 8,
                tooltipY: 0,
                fill: am5.color(0xff8c00)
            }));
            const circle2 = container.children.push(am5.Circle.new(root, {
                radius: 12,
                fillOpacity: 0.3,
                tooltipY: 0,
                fill: am5.color(0xff8c00)
            }));
            const circle3 = container.children.push(am5.Circle.new(root, {
                radius: 16,
                fillOpacity: 0.3,
                tooltipY: 0,
                fill: am5.color(0xff8c00)
            }));
            const label = container.children.push(am5.Label.new(root, {
                centerX: am5.p50,
                centerY: am5.p50,
                fill: am5.color(0xffffff),
                populateText: true,
                fontSize: "8",
                text: "{value}"
            }));
            container.events.on("click", function (e) {
                pointSeries.zoomToCluster(e.target.dataItem);
            });
            return am5.Bullet.new(root, {
                sprite: container
            });
        });
        pointSeries.bullets.push(function () {
            const circle = am5.Circle.new(root, {
                radius: 6,
                tooltipY: 0,
                fill: am5.color(0xff8c00),
                tooltipText: "{title}"
            });
            return am5.Bullet.new(root, {
                sprite: circle
            });
        });
        const cities = [
            { title: "Vienna \nMac OS \nIP: 192.168.1.1", latitude: 48.2092, longitude: 16.3728 },
            { title: "Minsk", latitude: 53.9678, longitude: 27.5766 },
            { title: "Brussels", latitude: 50.8371, longitude: 4.3676 },
            { title: "Sarajevo", latitude: 43.8608, longitude: 18.4214 },
            { title: "Sofia", latitude: 42.7105, longitude: 23.3238 },
        ];
        for (let i = 0; i < safeData.length; i++) {
            const city = safeData[i];
            addCity(city.longitude, city.latitude, city.title);
        }

        function addCity(longitude, latitude, title) {
            pointSeries.data.push({
                geometry: { type: "Point", coordinates: [longitude, latitude] },
                title: title
            });
        }
        chart.appear(1000, 100);
    }
    renderGraph(el, options) {
        if (!el) {
            console.warn('ApexCharts: DOM element is null or undefined');
            return;
        }
        const graphData = new ApexCharts(el, options);
        graphData.render();
    }
    viewProperties(type) {
        let domain, context;
        let name = this.getPropertyName(type);
        if (type === 'all') {
            domain = []
        } else {
            domain = [['stage', '=', type]]
        }
        context = { 'create': false }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: 'property.details',
            view_mode: 'kanban',
            views: [[false, 'tree'], [false, 'kanban'], [false, 'form']],
            target: 'current',
            context: context,
            domain: domain,
        });
    }
    viewPartner(type) {
        let name = "";
        if (type == 'customer') {
            name = "Customers"
        } else if (type == 'landlord') {
            name = 'Landlords'
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: 'res.partner',
            view_mode: 'kanban',
            views: [[false, 'kanban'], [false, 'tree'], [false, 'form']],
            target: 'current',
            context: { 'create': false },
            domain: [['user_type', '=', type]],
        });
    }
    viewPropertySale(type) {
        let domain, context;
        let model = 'property.vendor'
        let name = this.getPropertyName(type);
        domain = [['stage', '=', type]]
        if (type == 'not_paid') {
            domain = [['payment_state', '=', 'not_paid'], ['sold_property_id', '!=', false]]
            model = 'account.move'
        }
        context = { 'create': false }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: model,
            view_mode: 'kanban',
            views: [[false, 'tree'], [false, 'form']],
            target: 'current',
            context: context,
            domain: domain,
        });
    }
    viewPropertyTenancies(type) {
        let domain, context, model;
        let name = this.getPropertyName(type);
        if (type === 'rent_total') {
            domain = ['|', ['type', '=', 'rent'], ['type', '=', 'full_rent']]
            model = 'rent.invoice'
        } else if (type === 'not_paid') {
            domain = [['payment_state', '=', type]]
            model = 'rent.invoice'
        } else if (type === 'extend_contract') {
            model = 'tenancy.details'
            domain = [['is_extended', '=', true]]
        } else {
            model = 'tenancy.details'
            domain = [['contract_type', '=', type]]
        }
        context = { 'create': false }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: model,
            view_mode: 'tree',
            views: [[false, 'tree'], [false, 'form']],
            target: 'current',
            context: context,
            domain: domain,
        });
    }
    viewStatistic(type) {
        let name = ""
        let model = ""
        let context = { 'create': false }
        if (type == 'region') {
            name = "Regions"
            model = "property.region"
        } else if (type == 'project') {
            name = "Projects"
            model = "property.project"
        } else if (type == 'sub_project') {
            name = "Sub Projects"
            model = "property.sub.project"
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: model,
            view_mode: 'tree',
            views: [[false, 'tree'], [false, 'form']],
            target: 'current',
            context: context,
        });

    }
    getPropertyName(type) {
        let name;
        if (type === 'all') {
            name = 'All Properties';
        } else if (type === 'booked') {
            name = 'Booked Properties'
        } else if (type === 'sale') {
            name = 'OnSale Properties'
        } else if (type === 'on_lease') {
            name = 'On Leased Properties'
        } else if (type === 'sold') {
            name = 'Sold Properties'
        } else if (type === 'available') {
            name = 'Available Properties'
        } else if (type === 'sold_total') {
            name = 'Sold Properties Total'
        } else if (type === 'new_contract') {
            name = 'Draft Contract'
        } else if (type === 'running_contract') {
            name = 'Running Contract'
        } else if (type === 'expire_contract') {
            name = 'Expire Contract'
        } else if (type === 'rent_total') {
            name = 'Total Rent Amount'
        } else if (type === 'not_paid') {
            name = 'Pending Invoice'
        } else if (type === 'close_contract') {
            name = 'Close Contracts'
        } else if (type === 'extend_contract') {
            name = 'Extended Contracts'
        } else if (type === 'refund') {
            name = 'Refunded Sale Contracts'
        }
        else {
            name = 'Properties'
        }
        return name;
    }
}
PropertyDashboard.template = "cjg_finance_property.property_dashboard";
registry.category("actions").add("property_dashboard", PropertyDashboard);
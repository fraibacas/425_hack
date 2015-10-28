/*****************************************************************************
 *
 * Copyright (C) Zenoss, Inc. 2014, all rights reserved.
 *
 * This content is made available according to terms specified in
 * License.zenoss under the directory where your Zenoss product is installed.
 *
 ****************************************************************************/


(function(){
    // Feature test for appropriate zoom cursor style.
    var selectCursorStyle = function() {
        var d = document.createElement('div');
        for (var i = 0; i < arguments.length; ++i) {
            d.style.cursor = arguments[i];
            if (d.style.cursor.length > 0) {
                return d.style.cursor;
            }
        }
        return '';
    };

    var zoomInCursorStyle = selectCursorStyle(
            "-webkit-zoom-in", "-moz-zoom-in", "crosshair"),
        zoomOutCursorStyle = selectCursorStyle(
            "-webkit-zoom-out", "-moz-zoom-out", "crosshair"),
        DATE_RANGES = [
            [129600, _t('Hourly')],
            [864000, _t('Daily')],
            [3628800, _t('Weekly')],
            [41472000, _t('Monthly')],
            [62208000, _t('Yearly')]
        ],
        // If a given request is over GRAPHPAGESIZE then the results
        // will be paginated.  Give IE a lower value it can handle.
        GRAPHPAGESIZE = Ext.isIE ? 25 : 50;

    /**********************************************************************
     *
     * Swoopy
     *
     */
    function fixBase64Padding(s) {
        s = s.split('=',1)[0];
        var a = [s];
        for (var i = 0; i <= 4 - (s.length % 4); i++) {
            a.push('=');
        }
        return a.join('');
    }

    var ZenGraphs = ZenGraphs || {},
        zoom_factor = 1.5,
        pan_factor = 3;

    Ext.ns('Zenoss');

    Zenoss.SWOOP_CALLBACKS = {};

    Zenoss.SwoopyGraph = Ext.extend(Ext.Panel, {
        constructor: function(config) {
            config = Ext.applyIf(config||{}, {
                html: {
                    tag: 'img',
                    src: config.graphUrl,
                    id: config.graphId,
                    style: 'cursor: ' + zoomInCursorStyle
                },
                width: 607,
                cls: 'graph-panel',
                tbar: {
                    items: [{
                        xtype: 'tbtext',
                        text: config.graphTitle
                    },'->',{
                        text: '&lt;',
                        width: 67,
                        handler: Ext.bind(function(btn, e) {
                            this.onPanLeft(this);
                        }, this)
                    },{
                        text: _t('Zoom In'),
                        enableToggle: true,
                        pressed: true,
                        ref: '../zoomin',
                        handler: Ext.bind(function(btn, e) {
                            this.fireEventsToAll("zoommodechange", this, !btn.pressed);
                        }, this)
                    },{
                        text: _t('Zoom Out'),
                        ref: '../zoomout',
                        enableToggle: true,
                        handler: Ext.bind(function(btn, e) {
                            this.fireEventsToAll("zoommodechange", this, btn.pressed);
                        }, this)
                    },{
                        text: '&gt;',
                        width: 67,
                        handler: Ext.bind(function(btn, e) {
                            this.onPanRight(this);
                        }, this)
                    }]
                }
            });
            Zenoss.SwoopyGraph.superclass.constructor.call(this, config);
        },
        initEvents: function() {
            this.addEvents("zoommodechange", "updateimage");
            Zenoss.SwoopyGraph.superclass.initEvents.call(this);
            this.on("zoommodechange", this.onZoomModeChange, this);
            this.on("updateimage", this.updateImage, this);
            this.graphEl = Ext.get(this.graphId);
            this.graphEl.on('click', this.onGraphClick, this);
            this.graphEl.on('load', function(){
                this.suspendLayouts();
                var size = this.graphEl.getSize();
                // set out panel to be the size of the graph
                // plus a little for the padding
                this.setWidth(size.width + 10);
                this.setHeight(size.height + 42);
                this.el.setHeight(size.height + 42); /* this line is for chrome */
                if (!size.width || !size.height){
                    this.showFailure();
                } else {
                    this.parseGraphParams();
                }
                this.resumeLayouts(true);
            }, this, {single:true});
            this.graphEl.on('error',
                function() { this.showFailure(); }, this);
        },
        showFailure: function() {
            this.failureMask = this.failureMask || Ext.DomHelper.insertAfter(this.graphEl, {
                tag: 'div',
                html: _t("There was a problem rendering this graph. Either the file does not exist or an error has occurred.  Initial graph creation can take up to 5 minutes.  If the graph still does not appear, please contact the administrator for this system."),
                width: this.graphEl.parent().getWidth(),
                height: this.graphEl.parent().getHeight()
            });
            var el = Ext.fly(this.failureMask);
            Ext.fly(this.failureMask).setDisplayed(true);
            this.graphEl.setDisplayed(false);
        },
        hideFailure: function() {
            if (this.failureMask) {
                this.graphEl.setDisplayed(true);
                Ext.fly(this.failureMask).setDisplayed(false);
            }
        },
        parseGraphParams: function(url) {
            url = url || this.graphEl.dom.src;
            var href = url.split('?'),
                gp = Ext.apply({url:href[0]}, Ext.urlDecode(href[1])),
                getSeconds = function(valueField, defaultValue) {
                    if (!Ext.isDefined(valueField)) {
                        return defaultValue;
                    }
                    var groups = /(now|end)-([0-9]*)s/.exec(valueField);
                    return Array.isArray(groups) ? Number(groups[2]) : defaultValue;
                };
            // Encoding can screw with the '=' padding at the end of gopts, so
            // strip and recreate it
            gp.gopts = fixBase64Padding(gp.gopts);
            gp.width = Number(gp.width);
            gp.drange = Number(gp.drange);
            gp.start = getSeconds(gp.start, gp.drange);
            gp.end = getSeconds(gp.end, 0);
            this.graph_params = gp;
        },
        fireEventsToAll: function() {
            if (this.linked()) {
                var args = arguments;
                Ext.each(this.refOwner.getGraphs(), function(g) {
                    g.fireEvent.apply(g, args);
                });
            } else {
                this.fireEvent.apply(this, arguments);
            }
        },
        linked: function() {
            return this.isLinked;
        },
        setLinked: function(isLinked) {
            this.isLinked = isLinked;
        },
        updateImage: function(params) {
            /*
             * params should look like:
             * {drange:n, start:n, end:n}
             */
            var gp = Ext.apply({}, params, this.graph_params);
            gp.end = 'now-' + gp.end + 's';
            gp.start = 'end-' + gp.start + 's';
            this.sendRequest(gp);
        },
        sendRequest: function(params) {
            var url = params.url,
                now = new Date().getTime(),
                graphid = now + '_' + this.graphId;
            delete params.url;
            params.graphid = graphid;

            var fullurl = Ext.urlAppend(url, Ext.urlEncode(params));
            this.graphEl.dom.src = fullurl;
            this.parseGraphParams(fullurl);
        },
        onPanLeft: function(graph) {
            var gp = this.graph_params;
            var delta = Math.round(gp.drange/pan_factor);
            var newend = gp.end + delta > 0 ? gp.end + delta : 0;
            this.fireEventsToAll("updateimage", {end:newend});
        },
        onPanRight: function(graph) {
            var gp = this.graph_params;
            var delta = Math.round(gp.drange/pan_factor);
            var newend = gp.end - delta > 0 ? gp.end - delta : 0;
            this.fireEventsToAll("updateimage", {end:newend});
        },
        onZoomModeChange: function(graph, zoomOut) {
            this.zoomout.toggle(zoomOut);
            this.zoomin.toggle(!zoomOut);
            this.graphEl.setStyle({
                'cursor': zoomOut ? zoomOutCursorStyle : zoomInCursorStyle
            });
        },
        doZoom: function(xpos, factor) {
            var gp = this.graph_params;
            if (xpos < 0 || xpos > gp.width) {
                return;
            }
            var drange = Math.round(gp.drange/factor),
                delta = ((gp.width/2) - xpos) * (gp.drange/gp.width) + (gp.drange - drange)/2,
                end = Math.round(gp.end + delta >= 0 ? gp.end + delta : 0);
            this.fireEventsToAll("updateimage", {
                drange: drange,
                start: drange,
                end: end
            });
        },
        onGraphClick: function(e) {
            var graph = e.getTarget(null, null, true),
                x = e.getPageX() - graph.getX() - 67,
            func = this.zoomin.pressed ? this.onZoomIn : this.onZoomOut;
            func.call(this, this, x);
        },
        onZoomIn: function(graph, xpos) {
            this.doZoom(xpos, zoom_factor);
        },
        onZoomOut: function(graph, xpos) {
            this.doZoom(xpos, 1/zoom_factor);
        }});

    /**********************************************************************
     *
     * Graph Panel
     *
     */
    var router = Zenoss.remote.DeviceRouter,
        GraphPanel,
        DRangeSelector,
        GraphRefreshButton,
        tbarConfig;

    Ext.define("Zenoss.form.GraphRefreshButton", {
        alias:['widget.graphrefreshbutton'],
        extend:"Zenoss.RefreshMenuButton",
        constructor: function(config) {
            config = config || {};
            var menu = {
                xtype: 'statefulrefreshmenu',
                id: config.stateId || Ext.id(),
                trigger: this,
                items: [{
                    cls: 'refreshevery',
                    text: 'Refresh every'
                },{
                    xtype: 'menucheckitem',
                    text: '1 minute',
                    value: 60,
                    group: 'refreshgroup'
                },{
                    xtype: 'menucheckitem',
                    text: '5 minutes',
                    value: 300,
                    group: 'refreshgroup'
                },{
                    xtype: 'menucheckitem',
                    text: '10 Minutes',
                    value: 600,
                    group: 'refreshgroup'
                },{
                    xtype: 'menucheckitem',
                    text: '30 Minutes',
                    checked: true,
                    value: 1800,
                    group: 'refreshgroup'
                },{
                    xtype: 'menucheckitem',
                    text: '1 Hour',
                    value: 3600,
                    group: 'refreshgroup'
                },{
                    xtype: 'menucheckitem',
                    text: 'Manually',
                    value: -1,
                    group: 'refreshgroup'
                }]
            };
            Ext.apply(config, {
                menu: menu
            });
            this.callParent(arguments);
        }
    });



    Ext.define("Zenoss.form.DRangeSelector", {
        alias:['widget.drangeselector'],
        extend:"Ext.form.ComboBox",
        constructor: function(config) {
            config = config || {};
            Ext.apply(config, {
                fieldLabel: _t('Range'),
                    name: 'ranges',
                    editable: false,
                    forceSelection: true,
                    autoSelect: true,
                    triggerAction: 'all',
                    value: 129600,
                    queryMode: 'local',
                    store: new Ext.data.ArrayStore({
                        id: 0,
                        model: 'Zenoss.model.IdName',
                        data: DATE_RANGES
                    }),
                    valueField: 'id',
                    displayField: 'name'
            });
            this.callParent(arguments);
        }
    });


    selectCustomDateRange = function(button,panel) {
        selectCustomDateRangeWindow = Ext.create('Zenoss.dialog.BaseWindow', {
            title: _t('Select custom date range'),
            id: 'selectCustomDateRangeWindow',
            width: 340,
            height: 120,
            layout:'fit',
            resizable: false,
            modal: true,
            plain: true,
            items: [{
               xtype: 'form',
               layout: 'column',
               defaults: { xtype: 'form' },
               items: [{
                   defaults: {
                       columnWidth:0.5,
                       xtype: 'datefield',
                       format : 'Y-m-d',
                       submitFormat: 'U',
                       vtype: 'linkedDateField',
                       maxValue: new Date(),
                       editable: false
                   },
                   items:[{
                       allowBlank: false,
                       name: 'StartDate',
                       fieldLabel: _t('Start Date/Time')
                   }, {
                       name: 'EndDate',
                       fieldLabel: _t('End Date/Time')
                   }]
               },{
                   defaults: {
                       submitFormat: 'U',
                       xtype: 'timefield',
                       vtype: 'linkedTimeField',
                       columnWidth: 0.1,
                       format: 'G:i',
                       border: true,
                       width: 60,
                       height: 20,
                       increment: 5,
                       autoScroll: true,
                       singleSelect: true,
                       emptyText: "0:00",
                       editable: false
                   },
                   items:[{
                       margin: '0 0 5 5',
                       name: 'StartTime'
                   }, {
                       margin: '0 0 0 5',
                       name: 'EndTime'
                   }]
               }],
               buttons: [{
                   text: _t('Submit'),
                   formBind: true,
                   xtype: 'DialogButton',
                   handler: function (button) {
                       var f = button.up('form').getForm()
                           edf = f.findField('EndDate'),
                           sdf = f.findField('StartDate'),
                           etf = f.findField('EndTime'),
                           stf = f.findField('StartTime'),
                           now = Math.floor(new Date().getTime() / 1000);

                       var start_date = sdf.getValue();

                       if (stf.getSubmitValue()) {
                           start_date.setHours(stf.getValue().getHours())
                           start_date.setMinutes(stf.getValue().getMinutes())
                       }

                       var end_date = edf.getValue();
                       if (!end_date) end_date = now;

                       if (etf.getSubmitValue()) {
                           end_date.setHours(etf.getValue().getHours())
                           end_date.setMinutes(etf.getValue().getMinutes())
                       }

                       end_date = Math.floor(end_date.getTime() / 1000)
                       start_date = Math.floor(start_date.getTime() / 1000)

                       panel.setDrange(end_date - start_date, now - end_date);
                   }
               },{
                   text: _t('Cancel'),
                   xtype: 'DialogButton'
               }]
            }]
        });
        selectCustomDateRangeWindow.show();
    }

    tbarConfig = [{
                    xtype: 'tbtext',
                    text: _t('Performance Graphs')
                }, '-', '->', {
                    xtype: 'drangeselector',
                    ref: '../drange_select',
                    listeners: {
                        select: function(combo, records, index){
                            var value = records[0].data.id,
                                panel = combo.refOwner;

                            panel.setDrange(value);
                        }
                    }
                },'-', {
                    xtype: 'button',
                    text: _t('Custom Range'),
                    tooltip: _t('Select custom range'),
                    ref: '../custom_range_select',
                    handler: function (btn) {
                        selectCustomDateRange(btn,btn.refOwner)
                        }
                },'-', {
                    xtype: 'button',
                    ref: '../resetBtn',
                    text: _t('Reset'),
                    handler: function(btn) {
                        var panel = btn.refOwner;
                        panel.setDrange();
                    }
                },'-',{
                    xtype: 'tbtext',
                    text: _t('Link Graphs?:')
                },{
                    xtype: 'checkbox',
                    ref: '../linkGraphs',
                    checked: true,
                    listeners: {
                        change: function(chkBx, checked) {
                            var panel = chkBx.refOwner;
                            panel.setLinked(checked);
                        }
                    }
                }, '-',{
                    xtype: 'graphrefreshbutton',
                    ref: '../refreshmenu',
                    stateId: 'graphRefresh',
                    iconCls: 'refresh',
                    text: _t('Refresh'),
                    handler: function(btn) {
                        if (btn) {
                            var panel = btn.refOwner;
                            panel.resetSwoopies();
                        }
                    }
                }];

    Ext.define("Zenoss.form.GraphPanel", {
        alias:['widget.graphpanel'],
        extend:"Ext.Panel",
        constructor: function(config) {
            config = config || {};
            // default to showing the toolbar
            if (!Ext.isDefined(config.showToolbar) ) {
                config.showToolbar = true;
            }
            if (config.showToolbar){
                config.tbar = tbarConfig;
            }
            Ext.applyIf(config, {
                drange: 129600,
                isLinked: true,
                // images show up after Ext has calculated the
                // size of the div
                bodyStyle: {
                    overflow: 'auto'
                },
                directFn: router.getGraphDefs
            });
            Zenoss.form.GraphPanel.superclass.constructor.apply(this, arguments);
        },
        setContext: function(uid) {
            // remove all the graphs
            this.removeAll();
            this.lastShown = 0;

            var params = {
                uid: uid,
                drange: this.drange
            };
            this.uid = uid;
            this.directFn(params, Ext.bind(this.loadGraphs, this));
        },
        loadGraphs: function(result){
            if (!result.success){
                return;
            }
            var data = result.data,
                panel = this,
                el = this.getEl();

            if (el.isMasked()) {
                el.unmask();
            }

            if (data.length > 0){
                this.addGraphs(data);
            }else{
                el.mask(_t('No Graph Data') , 'x-mask-msg-noicon');
            }
        },
        addGraphs: function(data) {
            var graphs = [],
                graph,
                graphId,
                me = this,
                start = this.lastShown,
                end = this.lastShown + GRAPHPAGESIZE,
                i;
            // load graphs until we have either completed the page or
            // we ran out of graphs
            for (i=start; i < Math.min(end, data.length); i++) {
                graphId = Ext.id();
                graph = data[i];
                graphs.push(new Zenoss.SwoopyGraph({
                    graphUrl: graph.url,
                    graphTitle: graph.title,
                    graphId: graphId,
                    isLinked: this.isLinked,
                    height: 250,
                    ref: graphId
                }));
            }

            // set up for the next page
            this.lastShown = end;

            // if we have more to show, add a button
            if (data.length > end) {
                graphs.push({
                    xtype: 'button',
                    margin: '0 0 7 7',
                    text: _t('Show more results...'),
                    handler: function(t) {
                        t.hide();
                        // will show the next page by looking at this.lastShown
                        me.addGraphs(data);
                    }
                });
            }

            // render the graphs
            this.add(graphs);
        },
        setDrange: function(drange,end) {
            drange = drange || this.drange;
            end = end || 0;
            this.drange = drange;
            Ext.each(this.getGraphs(), function(g) {
                g.fireEvent("updateimage", {
                    drange: drange,
                    start: drange,
                    end: end
                }, this);
            });
        },
        resetSwoopies: function() {
            Ext.each(this.getGraphs(), function(g) {
                g.fireEvent("updateimage", {
                }, this);
            });
        },
        getGraphs: function() {
            var graphs = Zenoss.util.filter(this.items.items, function(item){
                return item.graphUrl;
            });
            return graphs;
        },
        setLinked: function(isLinked) {
            this.isLinked = isLinked;
            Ext.each(this.getGraphs(), function(g){
                g.setLinked(isLinked);
            });
        }
    });



}());

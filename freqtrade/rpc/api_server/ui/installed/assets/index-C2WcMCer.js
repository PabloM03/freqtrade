import{Z as T,aa as w,c as u,a as c,a1 as h,N as d,ab as O,F as N,k as $,V as C,X as j,l as k,h as R,ac as _,n as P,H as U,e as m,d as Z,u as G,r as Q,j as X,A as I,G as q,b as K,s as J,f as v,i as Y,m as tt,E as et,x as at,z as nt,t as rt,ad as st,ae as F,af as D,ag as S,ah as it,ai as V,aj as ot,ak as B,al as lt,am as E,an as M,ao as ct,ap as x}from"./index-B2VjJQTc.js";import{a as dt,b as ut}from"./InfoBox.vue_vue_type_script_setup_true_lang-CUmi5isc.js";import{b as bt}from"./index-Hl3UVVNC.js";var pt=`
    .p-tabs {
        display: flex;
        flex-direction: column;
    }

    .p-tablist {
        display: flex;
        position: relative;
    }

    .p-tabs-scrollable > .p-tablist {
        overflow: hidden;
    }

    .p-tablist-viewport {
        overflow-x: auto;
        overflow-y: hidden;
        scroll-behavior: smooth;
        scrollbar-width: none;
        overscroll-behavior: contain auto;
    }

    .p-tablist-viewport::-webkit-scrollbar {
        display: none;
    }

    .p-tablist-tab-list {
        position: relative;
        display: flex;
        background: dt('tabs.tablist.background');
        border-style: solid;
        border-color: dt('tabs.tablist.border.color');
        border-width: dt('tabs.tablist.border.width');
    }

    .p-tablist-content {
        flex-grow: 1;
    }

    .p-tablist-nav-button {
        all: unset;
        position: absolute !important;
        flex-shrink: 0;
        inset-block-start: 0;
        z-index: 2;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: dt('tabs.nav.button.background');
        color: dt('tabs.nav.button.color');
        width: dt('tabs.nav.button.width');
        transition:
            color dt('tabs.transition.duration'),
            outline-color dt('tabs.transition.duration'),
            box-shadow dt('tabs.transition.duration');
        box-shadow: dt('tabs.nav.button.shadow');
        outline-color: transparent;
        cursor: pointer;
    }

    .p-tablist-nav-button:focus-visible {
        z-index: 1;
        box-shadow: dt('tabs.nav.button.focus.ring.shadow');
        outline: dt('tabs.nav.button.focus.ring.width') dt('tabs.nav.button.focus.ring.style') dt('tabs.nav.button.focus.ring.color');
        outline-offset: dt('tabs.nav.button.focus.ring.offset');
    }

    .p-tablist-nav-button:hover {
        color: dt('tabs.nav.button.hover.color');
    }

    .p-tablist-prev-button {
        inset-inline-start: 0;
    }

    .p-tablist-next-button {
        inset-inline-end: 0;
    }

    .p-tablist-prev-button:dir(rtl),
    .p-tablist-next-button:dir(rtl) {
        transform: rotate(180deg);
    }

    .p-tab {
        flex-shrink: 0;
        cursor: pointer;
        user-select: none;
        position: relative;
        border-style: solid;
        white-space: nowrap;
        gap: dt('tabs.tab.gap');
        background: dt('tabs.tab.background');
        border-width: dt('tabs.tab.border.width');
        border-color: dt('tabs.tab.border.color');
        color: dt('tabs.tab.color');
        padding: dt('tabs.tab.padding');
        font-weight: dt('tabs.tab.font.weight');
        transition:
            background dt('tabs.transition.duration'),
            border-color dt('tabs.transition.duration'),
            color dt('tabs.transition.duration'),
            outline-color dt('tabs.transition.duration'),
            box-shadow dt('tabs.transition.duration');
        margin: dt('tabs.tab.margin');
        outline-color: transparent;
    }

    .p-tab:not(.p-disabled):focus-visible {
        z-index: 1;
        box-shadow: dt('tabs.tab.focus.ring.shadow');
        outline: dt('tabs.tab.focus.ring.width') dt('tabs.tab.focus.ring.style') dt('tabs.tab.focus.ring.color');
        outline-offset: dt('tabs.tab.focus.ring.offset');
    }

    .p-tab:not(.p-tab-active):not(.p-disabled):hover {
        background: dt('tabs.tab.hover.background');
        border-color: dt('tabs.tab.hover.border.color');
        color: dt('tabs.tab.hover.color');
    }

    .p-tab-active {
        background: dt('tabs.tab.active.background');
        border-color: dt('tabs.tab.active.border.color');
        color: dt('tabs.tab.active.color');
    }

    .p-tabpanels {
        background: dt('tabs.tabpanel.background');
        color: dt('tabs.tabpanel.color');
        padding: dt('tabs.tabpanel.padding');
        outline: 0 none;
    }

    .p-tabpanel:focus-visible {
        box-shadow: dt('tabs.tabpanel.focus.ring.shadow');
        outline: dt('tabs.tabpanel.focus.ring.width') dt('tabs.tabpanel.focus.ring.style') dt('tabs.tabpanel.focus.ring.color');
        outline-offset: dt('tabs.tabpanel.focus.ring.offset');
    }

    .p-tablist-active-bar {
        z-index: 1;
        display: block;
        position: absolute;
        inset-block-end: dt('tabs.active.bar.bottom');
        height: dt('tabs.active.bar.height');
        background: dt('tabs.active.bar.background');
        transition: 250ms cubic-bezier(0.35, 0, 0.25, 1);
    }
`,ft={root:function(t){var n=t.props;return["p-tabs p-component",{"p-tabs-scrollable":n.scrollable}]}},vt=T.extend({name:"tabs",style:pt,classes:ft}),ht={name:"BaseTabs",extends:w,props:{value:{type:[String,Number],default:void 0},lazy:{type:Boolean,default:!1},scrollable:{type:Boolean,default:!1},showNavigators:{type:Boolean,default:!0},tabindex:{type:Number,default:0},selectOnFocus:{type:Boolean,default:!1}},style:vt,provide:function(){return{$pcTabs:this,$parentInstance:this}}},mt={name:"Tabs",extends:ht,inheritAttrs:!1,emits:["update:value"],data:function(){return{d_value:this.value}},watch:{value:function(t){this.d_value=t}},methods:{updateValue:function(t){this.d_value!==t&&(this.d_value=t,this.$emit("update:value",t))},isVertical:function(){return this.orientation==="vertical"}}};function gt(e,t,n,r,o,a){return c(),u("div",d({class:e.cx("root")},e.ptmi("root")),[h(e.$slots,"default")],16)}mt.render=gt;var yt={root:"p-tabpanels"},$t=T.extend({name:"tabpanels",classes:yt}),kt={name:"BaseTabPanels",extends:w,props:{},style:$t,provide:function(){return{$pcTabPanels:this,$parentInstance:this}}},Tt={name:"TabPanels",extends:kt,inheritAttrs:!1};function wt(e,t,n,r,o,a){return c(),u("div",d({class:e.cx("root"),role:"presentation"},e.ptmi("root")),[h(e.$slots,"default")],16)}Tt.render=wt;var Bt={root:function(t){var n=t.instance;return["p-tabpanel",{"p-tabpanel-active":n.active}]}},xt=T.extend({name:"tabpanel",classes:Bt}),Ct={name:"BaseTabPanel",extends:w,props:{value:{type:[String,Number],default:void 0},as:{type:[String,Object],default:"DIV"},asChild:{type:Boolean,default:!1},header:null,headerStyle:null,headerClass:null,headerProps:null,headerActionProps:null,contentStyle:null,contentClass:null,contentProps:null,disabled:Boolean},style:xt,provide:function(){return{$pcTabPanel:this,$parentInstance:this}}},_t={name:"TabPanel",extends:Ct,inheritAttrs:!1,inject:["$pcTabs"],computed:{active:function(){var t;return O((t=this.$pcTabs)===null||t===void 0?void 0:t.d_value,this.value)},id:function(){var t;return"".concat((t=this.$pcTabs)===null||t===void 0?void 0:t.$id,"_tabpanel_").concat(this.value)},ariaLabelledby:function(){var t;return"".concat((t=this.$pcTabs)===null||t===void 0?void 0:t.$id,"_tab_").concat(this.value)},attrs:function(){return d(this.a11yAttrs,this.ptmi("root",this.ptParams))},a11yAttrs:function(){var t;return{id:this.id,tabindex:(t=this.$pcTabs)===null||t===void 0?void 0:t.tabindex,role:"tabpanel","aria-labelledby":this.ariaLabelledby,"data-pc-name":"tabpanel","data-p-active":this.active}},ptParams:function(){return{context:{active:this.active}}}}};function Pt(e,t,n,r,o,a){var s,i;return a.$pcTabs?(c(),u(N,{key:1},[e.asChild?h(e.$slots,"default",{key:1,class:P(e.cx("root")),active:a.active,a11yAttrs:a.a11yAttrs}):(c(),u(N,{key:0},[!((s=a.$pcTabs)!==null&&s!==void 0&&s.lazy)||a.active?C((c(),k(_(e.as),d({key:0,class:e.cx("root")},a.attrs),{default:R(function(){return[h(e.$slots,"default")]}),_:3},16,["class"])),[[j,(i=a.$pcTabs)!==null&&i!==void 0&&i.lazy?!0:a.active]]):$("",!0)],64))],64)):h(e.$slots,"default",{key:0})}_t.render=Pt;const Lt={viewBox:"0 0 24 24",width:"1.2em",height:"1.2em"};function At(e,t){return c(),u("svg",Lt,t[0]||(t[0]=[m("path",{fill:"currentColor",d:"M12 17a2 2 0 0 0 2-2a2 2 0 0 0-2-2a2 2 0 0 0-2 2a2 2 0 0 0 2 2m6-9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2h1V6a5 5 0 0 1 5-5a5 5 0 0 1 5 5v2zm-6-5a3 3 0 0 0-3 3v2h6V6a3 3 0 0 0-3-3"},null,-1)]))}const St=U({name:"mdi-lock",render:At}),Nt={class:"divide-y divide-surface-300 dark:divide-surface-700 divide-solid border-x border-y rounded-sm border-surface-300 dark:border-surface-700"},Vt=["title","onClick"],zt=["title"],It=Z({__name:"PairSummary",props:{pairlist:{},currentLocks:{default:()=>[]},trades:{},sortMethod:{default:"normal"},backtestMode:{type:Boolean,default:!1},startingBalance:{default:0}},setup(e){const t=e,n=G(),r=Q(""),o=X(()=>{const a=[];return t.pairlist.forEach(s=>{const i=t.trades.filter(f=>f.pair===s),b=t.currentLocks.filter(f=>f.pair===s);let g="",p;b.sort((f,H)=>f.lock_end_timestamp>H.lock_end_timestamp?-1:1),b.length>0&&([p]=b,g=`${I(p.lock_end_timestamp)} - ${p.side} - ${p.reason}`);let l="",y=0,L=0;i.forEach(f=>{y+=f.profit_ratio,L+=f.profit_abs??0}),t.sortMethod=="profit"&&t.startingBalance&&(y=L/t.startingBalance);const z=i.length,A=z?i[0]:void 0;i.length>0&&(l=`Current profit: ${q(y)}`),A&&(l+=`
Open since: ${I(A.open_timestamp)}`),(r.value===""||s.toLocaleLowerCase().includes(r.value.toLocaleLowerCase()))&&a.push({pair:s,trade:A,locks:p,lockReason:g,profitString:l,profit:y,profitAbs:L,tradeCount:z})}),t.sortMethod==="profit"?a.sort((s,i)=>s.profit>i.profit?-1:1):a.sort((s,i)=>s.trade&&!i.trade?-1:s.trade&&i.trade?s.trade.trade_id>i.trade.trade_id?1:-1:!s.locks&&i.locks?-1:s.locks&&i.locks?s.locks.lock_end_timestamp>i.locks.lock_end_timestamp?1:-1:1),a});return(a,s)=>{const i=J,b=St,g=dt,p=ut;return c(),u("div",null,[m("div",{"label-for":"trade-filter",class:P(["mb-2",{"me-4":a.backtestMode,"me-2":!a.backtestMode}])},[K(i,{id:"trade-filter",modelValue:v(r),"onUpdate:modelValue":s[0]||(s[0]=l=>Y(r)?r.value=l:null),type:"text",placeholder:"Filter",class:"w-full"},null,8,["modelValue"])],2),m("ul",Nt,[(c(!0),u(N,null,tt(v(o),l=>(c(),u("li",{key:l.pair,button:"",class:P(["flex cursor-pointer last:rounded-b justify-between items-center px-1 py-1.5",{"bg-primary dark:border-primary text-primary-contrast":l.pair===v(n).activeBot.selectedPair}]),title:`${("formatPriceCurrency"in a?a.formatPriceCurrency:v(et))(l.profitAbs,v(n).activeBot.stakeCurrency,v(n).activeBot.stakeCurrencyDecimals)} - ${l.pair} - ${l.tradeCount} trades`,onClick:y=>v(n).activeBot.selectedPair=l.pair},[m("div",null,[at(nt(l.pair)+" ",1),l.locks?(c(),u("span",{key:0,title:l.lockReason},[K(b)],8,zt)):$("",!0)]),l.trade&&!a.backtestMode?(c(),k(g,{key:0,trade:l.trade},null,8,["trade"])):$("",!0),a.backtestMode&&l.tradeCount>0?(c(),k(p,{key:1,"profit-ratio":l.profit,"stake-currency":v(n).activeBot.stakeCurrency},null,8,["profit-ratio","stake-currency"])):$("",!0)],10,Vt))),128))])])}}}),ee=rt(It,[["__scopeId","data-v-7aba73a9"]]);var W={name:"ChevronLeftIcon",extends:st};function Kt(e,t,n,r,o,a){return c(),u("svg",d({width:"14",height:"14",viewBox:"0 0 14 14",fill:"none",xmlns:"http://www.w3.org/2000/svg"},e.pti()),t[0]||(t[0]=[m("path",{d:"M9.61296 13C9.50997 13.0005 9.40792 12.9804 9.3128 12.9409C9.21767 12.9014 9.13139 12.8433 9.05902 12.7701L3.83313 7.54416C3.68634 7.39718 3.60388 7.19795 3.60388 6.99022C3.60388 6.78249 3.68634 6.58325 3.83313 6.43628L9.05902 1.21039C9.20762 1.07192 9.40416 0.996539 9.60724 1.00012C9.81032 1.00371 10.0041 1.08597 10.1477 1.22959C10.2913 1.37322 10.3736 1.56698 10.3772 1.77005C10.3808 1.97313 10.3054 2.16968 10.1669 2.31827L5.49496 6.99022L10.1669 11.6622C10.3137 11.8091 10.3962 12.0084 10.3962 12.2161C10.3962 12.4238 10.3137 12.6231 10.1669 12.7701C10.0945 12.8433 10.0083 12.9014 9.91313 12.9409C9.81801 12.9804 9.71596 13.0005 9.61296 13Z",fill:"currentColor"},null,-1)]),16)}W.render=Kt;var Et={root:"p-tablist",content:function(t){var n=t.instance;return["p-tablist-content",{"p-tablist-viewport":n.$pcTabs.scrollable}]},tabList:"p-tablist-tab-list",activeBar:"p-tablist-active-bar",prevButton:"p-tablist-prev-button p-tablist-nav-button",nextButton:"p-tablist-next-button p-tablist-nav-button"},Ot=T.extend({name:"tablist",classes:Et}),Rt={name:"BaseTabList",extends:w,props:{},style:Ot,provide:function(){return{$pcTabList:this,$parentInstance:this}}},Ft={name:"TabList",extends:Rt,inheritAttrs:!1,inject:["$pcTabs"],data:function(){return{isPrevButtonEnabled:!1,isNextButtonEnabled:!0}},resizeObserver:void 0,watch:{showNavigators:function(t){t?this.bindResizeObserver():this.unbindResizeObserver()},activeValue:{flush:"post",handler:function(){this.updateInkBar()}}},mounted:function(){var t=this;setTimeout(function(){t.updateInkBar()},150),this.showNavigators&&(this.updateButtonState(),this.bindResizeObserver())},updated:function(){this.showNavigators&&this.updateButtonState()},beforeUnmount:function(){this.unbindResizeObserver()},methods:{onScroll:function(t){this.showNavigators&&this.updateButtonState(),t.preventDefault()},onPrevButtonClick:function(){var t=this.$refs.content,n=this.getVisibleButtonWidths(),r=S(t)-n,o=Math.abs(t.scrollLeft),a=r*.8,s=o-a,i=Math.max(s,0);t.scrollLeft=E(t)?-1*i:i},onNextButtonClick:function(){var t=this.$refs.content,n=this.getVisibleButtonWidths(),r=S(t)-n,o=Math.abs(t.scrollLeft),a=r*.8,s=o+a,i=t.scrollWidth-r,b=Math.min(s,i);t.scrollLeft=E(t)?-1*b:b},bindResizeObserver:function(){var t=this;this.resizeObserver=new ResizeObserver(function(){return t.updateButtonState()}),this.resizeObserver.observe(this.$refs.list)},unbindResizeObserver:function(){var t;(t=this.resizeObserver)===null||t===void 0||t.unobserve(this.$refs.list),this.resizeObserver=void 0},updateInkBar:function(){var t=this.$refs,n=t.content,r=t.inkbar,o=t.tabs;if(r){var a=V(n,'[data-pc-name="tab"][data-p-active="true"]');this.$pcTabs.isVertical()?(r.style.height=ot(a)+"px",r.style.top=B(a).top-B(o).top+"px"):(r.style.width=lt(a)+"px",r.style.left=B(a).left-B(o).left+"px")}},updateButtonState:function(){var t=this.$refs,n=t.list,r=t.content,o=r.scrollTop,a=r.scrollWidth,s=r.scrollHeight,i=r.offsetWidth,b=r.offsetHeight,g=Math.abs(r.scrollLeft),p=[S(r),it(r)],l=p[0],y=p[1];this.$pcTabs.isVertical()?(this.isPrevButtonEnabled=o!==0,this.isNextButtonEnabled=n.offsetHeight>=b&&parseInt(o)!==s-y):(this.isPrevButtonEnabled=g!==0,this.isNextButtonEnabled=n.offsetWidth>=i&&parseInt(g)!==a-l)},getVisibleButtonWidths:function(){var t=this.$refs,n=t.prevButton,r=t.nextButton,o=0;return this.showNavigators&&(o=(n?.offsetWidth||0)+(r?.offsetWidth||0)),o}},computed:{templates:function(){return this.$pcTabs.$slots},activeValue:function(){return this.$pcTabs.d_value},showNavigators:function(){return this.$pcTabs.scrollable&&this.$pcTabs.showNavigators},prevButtonAriaLabel:function(){return this.$primevue.config.locale.aria?this.$primevue.config.locale.aria.previous:void 0},nextButtonAriaLabel:function(){return this.$primevue.config.locale.aria?this.$primevue.config.locale.aria.next:void 0},dataP:function(){return D({scrollable:this.$pcTabs.scrollable})}},components:{ChevronLeftIcon:W,ChevronRightIcon:bt},directives:{ripple:F}},Dt=["data-p"],Mt=["aria-label","tabindex"],Wt=["data-p"],Ht=["aria-orientation"],jt=["aria-label","tabindex"];function Ut(e,t,n,r,o,a){var s=M("ripple");return c(),u("div",d({ref:"list",class:e.cx("root"),"data-p":a.dataP},e.ptmi("root")),[a.showNavigators&&o.isPrevButtonEnabled?C((c(),u("button",d({key:0,ref:"prevButton",type:"button",class:e.cx("prevButton"),"aria-label":a.prevButtonAriaLabel,tabindex:a.$pcTabs.tabindex,onClick:t[0]||(t[0]=function(){return a.onPrevButtonClick&&a.onPrevButtonClick.apply(a,arguments)})},e.ptm("prevButton"),{"data-pc-group-section":"navigator"}),[(c(),k(_(a.templates.previcon||"ChevronLeftIcon"),d({"aria-hidden":"true"},e.ptm("prevIcon")),null,16))],16,Mt)),[[s]]):$("",!0),m("div",d({ref:"content",class:e.cx("content"),onScroll:t[1]||(t[1]=function(){return a.onScroll&&a.onScroll.apply(a,arguments)}),"data-p":a.dataP},e.ptm("content")),[m("div",d({ref:"tabs",class:e.cx("tabList"),role:"tablist","aria-orientation":a.$pcTabs.orientation||"horizontal"},e.ptm("tabList")),[h(e.$slots,"default"),m("span",d({ref:"inkbar",class:e.cx("activeBar"),role:"presentation","aria-hidden":"true"},e.ptm("activeBar")),null,16)],16,Ht)],16,Wt),a.showNavigators&&o.isNextButtonEnabled?C((c(),u("button",d({key:1,ref:"nextButton",type:"button",class:e.cx("nextButton"),"aria-label":a.nextButtonAriaLabel,tabindex:a.$pcTabs.tabindex,onClick:t[2]||(t[2]=function(){return a.onNextButtonClick&&a.onNextButtonClick.apply(a,arguments)})},e.ptm("nextButton"),{"data-pc-group-section":"navigator"}),[(c(),k(_(a.templates.nexticon||"ChevronRightIcon"),d({"aria-hidden":"true"},e.ptm("nextIcon")),null,16))],16,jt)),[[s]]):$("",!0)],16,Dt)}Ft.render=Ut;var Zt={root:function(t){var n=t.instance,r=t.props;return["p-tab",{"p-tab-active":n.active,"p-disabled":r.disabled}]}},Gt=T.extend({name:"tab",classes:Zt}),Qt={name:"BaseTab",extends:w,props:{value:{type:[String,Number],default:void 0},disabled:{type:Boolean,default:!1},as:{type:[String,Object],default:"BUTTON"},asChild:{type:Boolean,default:!1}},style:Gt,provide:function(){return{$pcTab:this,$parentInstance:this}}},Xt={name:"Tab",extends:Qt,inheritAttrs:!1,inject:["$pcTabs","$pcTabList"],methods:{onFocus:function(){this.$pcTabs.selectOnFocus&&this.changeActiveValue()},onClick:function(){this.changeActiveValue()},onKeydown:function(t){switch(t.code){case"ArrowRight":this.onArrowRightKey(t);break;case"ArrowLeft":this.onArrowLeftKey(t);break;case"Home":this.onHomeKey(t);break;case"End":this.onEndKey(t);break;case"PageDown":this.onPageDownKey(t);break;case"PageUp":this.onPageUpKey(t);break;case"Enter":case"NumpadEnter":case"Space":this.onEnterKey(t);break}},onArrowRightKey:function(t){var n=this.findNextTab(t.currentTarget);n?this.changeFocusedTab(t,n):this.onHomeKey(t),t.preventDefault()},onArrowLeftKey:function(t){var n=this.findPrevTab(t.currentTarget);n?this.changeFocusedTab(t,n):this.onEndKey(t),t.preventDefault()},onHomeKey:function(t){var n=this.findFirstTab();this.changeFocusedTab(t,n),t.preventDefault()},onEndKey:function(t){var n=this.findLastTab();this.changeFocusedTab(t,n),t.preventDefault()},onPageDownKey:function(t){this.scrollInView(this.findLastTab()),t.preventDefault()},onPageUpKey:function(t){this.scrollInView(this.findFirstTab()),t.preventDefault()},onEnterKey:function(t){this.changeActiveValue(),t.preventDefault()},findNextTab:function(t){var n=arguments.length>1&&arguments[1]!==void 0?arguments[1]:!1,r=n?t:t.nextElementSibling;return r?x(r,"data-p-disabled")||x(r,"data-pc-section")==="activebar"?this.findNextTab(r):V(r,'[data-pc-name="tab"]'):null},findPrevTab:function(t){var n=arguments.length>1&&arguments[1]!==void 0?arguments[1]:!1,r=n?t:t.previousElementSibling;return r?x(r,"data-p-disabled")||x(r,"data-pc-section")==="activebar"?this.findPrevTab(r):V(r,'[data-pc-name="tab"]'):null},findFirstTab:function(){return this.findNextTab(this.$pcTabList.$refs.tabs.firstElementChild,!0)},findLastTab:function(){return this.findPrevTab(this.$pcTabList.$refs.tabs.lastElementChild,!0)},changeActiveValue:function(){this.$pcTabs.updateValue(this.value)},changeFocusedTab:function(t,n){ct(n),this.scrollInView(n)},scrollInView:function(t){var n;t==null||(n=t.scrollIntoView)===null||n===void 0||n.call(t,{block:"nearest"})}},computed:{active:function(){var t;return O((t=this.$pcTabs)===null||t===void 0?void 0:t.d_value,this.value)},id:function(){var t;return"".concat((t=this.$pcTabs)===null||t===void 0?void 0:t.$id,"_tab_").concat(this.value)},ariaControls:function(){var t;return"".concat((t=this.$pcTabs)===null||t===void 0?void 0:t.$id,"_tabpanel_").concat(this.value)},attrs:function(){return d(this.asAttrs,this.a11yAttrs,this.ptmi("root",this.ptParams))},asAttrs:function(){return this.as==="BUTTON"?{type:"button",disabled:this.disabled}:void 0},a11yAttrs:function(){return{id:this.id,tabindex:this.active?this.$pcTabs.tabindex:-1,role:"tab","aria-selected":this.active,"aria-controls":this.ariaControls,"data-pc-name":"tab","data-p-disabled":this.disabled,"data-p-active":this.active,onFocus:this.onFocus,onKeydown:this.onKeydown}},ptParams:function(){return{context:{active:this.active}}},dataP:function(){return D({active:this.active})}},directives:{ripple:F}};function qt(e,t,n,r,o,a){var s=M("ripple");return e.asChild?h(e.$slots,"default",{key:1,dataP:a.dataP,class:P(e.cx("root")),active:a.active,a11yAttrs:a.a11yAttrs,onClick:a.onClick}):C((c(),k(_(e.as),d({key:0,class:e.cx("root"),"data-p":a.dataP,onClick:a.onClick},a.attrs),{default:R(function(){return[h(e.$slots,"default")]}),_:3},16,["class","data-p","onClick"])),[[s]])}Xt.render=qt;export{ee as _,Ft as a,Xt as b,Tt as c,_t as d,mt as s};
//# sourceMappingURL=index-C2WcMCer.js.map

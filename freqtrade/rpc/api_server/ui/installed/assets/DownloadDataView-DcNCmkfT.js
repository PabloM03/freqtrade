import{_ as q}from"./DraggableContainer.vue_vue_type_script_setup_true_lang-DsE7-ojn.js";import{_ as G}from"./ExchangeSelect.vue_vue_type_script_setup_true_lang-plmNybvH.js";import{Z as K,aa as Q,af as j,c as i,a as s,k as w,N as T,a1 as ee,x as f,z as S,H as ne,e as n,d as O,c9 as te,l as v,F as C,m as P,b as o,f as r,g as A,h as p,B as se,j as ae,r as b,u as re,R as oe,S as ie,i as D,W as le,a2 as de,Y as z,V as M,c2 as ue,X as N,t as me}from"./index-B2VjJQTc.js";import{_ as ce,a as pe}from"./chevron-up-CnOWeWXS.js";import{s as _e}from"./index-Dy0tFh2_.js";import{_ as ge}from"./TimeRangeSelect.vue_vue_type_script_setup_true_lang-DMFvQMoE.js";import{_ as fe}from"./check-CI6y9Q_q.js";import"./plus-box-outline-CJYGTdMk.js";var be=`
    .p-progressbar {
        display: block;
        position: relative;
        overflow: hidden;
        height: dt('progressbar.height');
        background: dt('progressbar.background');
        border-radius: dt('progressbar.border.radius');
    }

    .p-progressbar-value {
        margin: 0;
        background: dt('progressbar.value.background');
    }

    .p-progressbar-label {
        color: dt('progressbar.label.color');
        font-size: dt('progressbar.label.font.size');
        font-weight: dt('progressbar.label.font.weight');
    }

    .p-progressbar-determinate .p-progressbar-value {
        height: 100%;
        width: 0%;
        position: absolute;
        display: none;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        transition: width 1s ease-in-out;
    }

    .p-progressbar-determinate .p-progressbar-label {
        display: inline-flex;
    }

    .p-progressbar-indeterminate .p-progressbar-value::before {
        content: '';
        position: absolute;
        background: inherit;
        inset-block-start: 0;
        inset-inline-start: 0;
        inset-block-end: 0;
        will-change: inset-inline-start, inset-inline-end;
        animation: p-progressbar-indeterminate-anim 2.1s cubic-bezier(0.65, 0.815, 0.735, 0.395) infinite;
    }

    .p-progressbar-indeterminate .p-progressbar-value::after {
        content: '';
        position: absolute;
        background: inherit;
        inset-block-start: 0;
        inset-inline-start: 0;
        inset-block-end: 0;
        will-change: inset-inline-start, inset-inline-end;
        animation: p-progressbar-indeterminate-anim-short 2.1s cubic-bezier(0.165, 0.84, 0.44, 1) infinite;
        animation-delay: 1.15s;
    }

    @keyframes p-progressbar-indeterminate-anim {
        0% {
            inset-inline-start: -35%;
            inset-inline-end: 100%;
        }
        60% {
            inset-inline-start: 100%;
            inset-inline-end: -90%;
        }
        100% {
            inset-inline-start: 100%;
            inset-inline-end: -90%;
        }
    }
    @-webkit-keyframes p-progressbar-indeterminate-anim {
        0% {
            inset-inline-start: -35%;
            inset-inline-end: 100%;
        }
        60% {
            inset-inline-start: 100%;
            inset-inline-end: -90%;
        }
        100% {
            inset-inline-start: 100%;
            inset-inline-end: -90%;
        }
    }

    @keyframes p-progressbar-indeterminate-anim-short {
        0% {
            inset-inline-start: -200%;
            inset-inline-end: 100%;
        }
        60% {
            inset-inline-start: 107%;
            inset-inline-end: -8%;
        }
        100% {
            inset-inline-start: 107%;
            inset-inline-end: -8%;
        }
    }
    @-webkit-keyframes p-progressbar-indeterminate-anim-short {
        0% {
            inset-inline-start: -200%;
            inset-inline-end: 100%;
        }
        60% {
            inset-inline-start: 107%;
            inset-inline-end: -8%;
        }
        100% {
            inset-inline-start: 107%;
            inset-inline-end: -8%;
        }
    }
`,ve={root:function(l){var d=l.instance;return["p-progressbar p-component",{"p-progressbar-determinate":d.determinate,"p-progressbar-indeterminate":d.indeterminate}]},value:"p-progressbar-value",label:"p-progressbar-label"},xe=K.extend({name:"progressbar",style:be,classes:ve}),he={name:"BaseProgressBar",extends:Q,props:{value:{type:Number,default:null},mode:{type:String,default:"determinate"},showValue:{type:Boolean,default:!0}},style:xe,provide:function(){return{$pcProgressBar:this,$parentInstance:this}}},J={name:"ProgressBar",extends:he,inheritAttrs:!1,computed:{progressStyle:function(){return{width:this.value+"%",display:"flex"}},indeterminate:function(){return this.mode==="indeterminate"},determinate:function(){return this.mode==="determinate"},dataP:function(){return j({determinate:this.determinate,indeterminate:this.indeterminate})}}},ke=["aria-valuenow","data-p"],ye=["data-p"],we=["data-p"],Se=["data-p"];function Ve(t,l,d,k,u,_){return s(),i("div",T({role:"progressbar",class:t.cx("root"),"aria-valuemin":"0","aria-valuenow":t.value,"aria-valuemax":"100","data-p":_.dataP},t.ptmi("root")),[_.determinate?(s(),i("div",T({key:0,class:t.cx("value"),style:_.progressStyle,"data-p":_.dataP},t.ptm("value")),[t.value!=null&&t.value!==0&&t.showValue?(s(),i("div",T({key:0,class:t.cx("label"),"data-p":_.dataP},t.ptm("label")),[ee(t.$slots,"default",{},function(){return[f(S(t.value+"%"),1)]})],16,we)):w("",!0)],16,ye)):_.indeterminate?(s(),i("div",T({key:1,class:t.cx("value"),"data-p":_.dataP},t.ptm("value")),null,16,Se)):w("",!0)],16,ke)}J.render=Ve;const $e={viewBox:"0 0 24 24",width:"1.2em",height:"1.2em"};function Te(t,l){return s(),i("svg",$e,l[0]||(l[0]=[n("path",{fill:"currentColor",d:"M8 17v-2h8v2zm8-7l-4 4l-4-4h2.5V7h3v3zM5 3h14a2 2 0 0 1 2 2v14c0 1.11-.89 2-2 2H5a2 2 0 0 1-2-2V5c0-1.1.9-2 2-2m0 2v14h14V5z"},null,-1)]))}const De=ne({name:"mdi-download-box-outline",render:Te}),Be={class:"flex flex-row items-end gap-1"},Ce={class:"ms-2 w-full grow space-y-1"},Pe=["title"],Ee={key:1},Ue={class:"flex justify-between"},ze={key:1},Me={key:2,class:"w-25"},Ne={key:3,class:"flex flex-col md:flex-row w-full grow gap-2"},Oe=O({__name:"BackgroundJobTracking",setup(t){const{runningJobs:l,clearJobs:d}=te();return(k,u)=>{const _=De,g=fe,x=J,y=se,h=A;return s(),i("div",Be,[n("ul",Ce,[(s(!0),i(C,null,P(r(l),(m,V)=>(s(),i("li",{key:V,class:"border p-1 pb-2 rounded-sm dark:border-surface-700 border-surface-300 flex gap-2 items-center",title:V},[m.taskStatus?.job_category==="download_data"?(s(),v(_,{key:0})):(s(),i("span",Ee,S(m.taskStatus?.job_category),1)),n("div",Ue,[m.taskStatus?.status==="success"?(s(),v(g,{key:0,class:"text-success",title:""})):(s(),i("span",ze,S(m.taskStatus?.status),1)),m.taskStatus?.progress?(s(),i("span",Me,S(m.taskStatus?.progress),1)):w("",!0)]),m.taskStatus?.progress?(s(),v(x,{key:2,class:"w-full grow",value:m.taskStatus?.progress/100*100,"show-progress":"",max:100,striped:""},null,8,["value"])):w("",!0),m.taskStatus?.progress_tasks?(s(),i("div",Ne,[(s(!0),i(C,null,P(Object.entries(m.taskStatus?.progress_tasks),([c,e])=>(s(),i("div",{key:c,class:"w-full"},[f(S(e.description)+" ",1),o(x,{class:"w-full grow",value:Math.round(e.progress/e.total*100*100)/100,"show-progress":"",pt:{value:{class:m.taskStatus.status==="success"?"bg-emerald-500":"bg-amber-500"}},striped:""},null,8,["value","pt"])]))),128))])):w("",!0)],8,Pe))),128))]),Object.keys(r(l)).length>0?(s(),v(h,{key:0,severity:"secondary",class:"ms-auto",onClick:r(d)},{icon:p(()=>[o(y)]),_:1},8,["onClick"])):w("",!0)])}}}),Ae=b([{description:"All USDT Pairs",pairs:[".*/USDT"]},{description:"All USDT Futures Pairs",pairs:[".*/USDT:USDT"]}]);function Je(){return{pairTemplates:ae(()=>Ae.value.map((t,l)=>({...t,idx:l})))}}const He={class:"px-1 mx-auto w-full max-w-4xl lg:max-w-7xl"},Re={class:"flex mb-3 gap-3 flex-col"},Fe={class:"flex flex-col gap-3"},Le={class:"flex flex-col lg:flex-row gap-3"},Ie={class:"flex-fill"},We={class:"flex flex-col gap-2"},Xe={class:"flex gap-2"},Ye={class:"flex flex-col gap-1"},Ze={class:"flex flex-col gap-1"},qe={class:"flex-fill px-3"},Ge={class:"flex flex-col gap-2"},Ke={class:"px-3 border dark:border-surface-700 border-surface-300 p-2 rounded-sm"},Qe={class:"flex flex-col gap-2"},je={class:"flex justify-between items-center"},en={key:0},nn={key:1,class:"flex items-center gap-2"},tn={class:"mb-2 border dark:border-surface-700 border-surface-300 rounded-sm p-2 text-start"},sn={class:"mb-2 border dark:border-surface-700 border-surface-300 rounded-md p-2 text-start"},an={class:"mb-2 border dark:border-surface-700 border-surface-300 rounded-md p-2 text-start"},rn={class:"px-3"},on=O({__name:"DownloadDataMain",setup(t){const l=re(),d=b(["BTC/USDT","ETH/USDT",""]),k=b(["5m","1h"]),u=b({useCustomTimerange:!1,timerange:"",days:30}),{pairTemplates:_}=Je(),g=b({customExchange:!1,selectedExchange:{exchange:"binance",trade_mode:{margin_mode:ie.NONE,trading_mode:oe.SPOT}}}),x=b(!1),y=b(!1),h=b(!1);function m(c){d.value.push(...c)}async function V(){const c={pairs:d.value.filter(e=>e!==""),timeframes:k.value.filter(e=>e!=="")};u.value.useCustomTimerange&&u.value.timerange?c.timerange=u.value.timerange:c.days=u.value.days,h.value&&(c.erase=x.value,c.download_trades=y.value,g.value.customExchange&&(c.exchange=g.value.selectedExchange.exchange,c.trading_mode=g.value.selectedExchange.trade_mode.trading_mode,c.margin_mode=g.value.selectedExchange.trade_mode.margin_mode)),await l.activeBot.startDataDownload(c)}return(c,e)=>{const H=Oe,E=ce,B=A,$=le,R=ge,F=_e,L=de,I=pe,W=ue,X=G,Y=q;return s(),i("div",He,[o(H,{class:"mb-4"}),o(Y,{header:"Downloading Data",class:"mx-1 p-4"},{default:p(()=>[n("div",Re,[n("div",Fe,[n("div",Le,[n("div",Ie,[n("div",We,[e[10]||(e[10]=n("div",{class:"flex justify-between"},[n("h4",{class:"text-start font-bold text-lg"},"Select Pairs"),n("h5",{class:"text-start font-bold text-lg"},"Pairs from template")],-1)),n("div",Xe,[o(E,{modelValue:r(d),"onUpdate:modelValue":e[0]||(e[0]=a=>D(d)?d.value=a:null),placeholder:"Pair",size:"small",class:"flex-grow-1"},null,8,["modelValue"]),n("div",Ye,[n("div",Ze,[(s(!0),i(C,null,P(r(_),a=>(s(),v(B,{key:a.idx,severity:"secondary",title:a.pairs.reduce((U,Z)=>`${U}${Z}
`,""),onClick:U=>m(a.pairs)},{default:p(()=>[f(S(a.description),1)]),_:2},1032,["title","onClick"]))),128))])])])])]),n("div",qe,[n("div",Ge,[e[11]||(e[11]=n("h4",{class:"text-start font-bold text-lg"},"Select timeframes",-1)),o(E,{modelValue:r(k),"onUpdate:modelValue":e[1]||(e[1]=a=>D(k)?k.value=a:null),placeholder:"Timeframe"},null,8,["modelValue"])])])]),n("div",Ke,[n("div",Qe,[n("div",je,[e[13]||(e[13]=n("h4",{class:"text-start mb-0 font-bold text-lg"},"Time Selection",-1)),o($,{modelValue:r(u).useCustomTimerange,"onUpdate:modelValue":e[2]||(e[2]=a=>r(u).useCustomTimerange=a),class:"mb-0",switch:""},{default:p(()=>e[12]||(e[12]=[f(" Use custom timerange ",-1)])),_:1,__:[12]},8,["modelValue"])]),r(u).useCustomTimerange?(s(),i("div",en,[o(R,{modelValue:r(u).timerange,"onUpdate:modelValue":e[3]||(e[3]=a=>r(u).timerange=a)},null,8,["modelValue"])])):(s(),i("div",nn,[e[14]||(e[14]=n("label",null,"Days to download:",-1)),o(F,{modelValue:r(u).days,"onUpdate:modelValue":e[4]||(e[4]=a=>r(u).days=a),type:"number","aria-label":"Days to download",min:1,step:1,size:"small"},null,8,["modelValue"])]))])]),n("div",tn,[o(B,{class:"mb-2",severity:"secondary",onClick:e[5]||(e[5]=a=>h.value=!r(h))},{default:p(()=>[e[15]||(e[15]=f(" Advanced Options ",-1)),r(h)?(s(),v(I,{key:1})):(s(),v(L,{key:0}))]),_:1,__:[15]}),o(z,null,{default:p(()=>[M(n("div",null,[o(W,{severity:"info",class:"mb-2 py-2"},{default:p(()=>e[16]||(e[16]=[f(" Advanced options (Erase data, Download trades, and Custom Exchange settings) will only be applied when this section is expanded. ",-1)])),_:1,__:[16]}),n("div",sn,[o($,{modelValue:r(x),"onUpdate:modelValue":e[6]||(e[6]=a=>D(x)?x.value=a:null),class:"mb-2"},{default:p(()=>e[17]||(e[17]=[f("Erase existing data",-1)])),_:1,__:[17]},8,["modelValue"]),o($,{modelValue:r(y),"onUpdate:modelValue":e[7]||(e[7]=a=>D(y)?y.value=a:null),class:"mb-2"},{default:p(()=>e[18]||(e[18]=[f(" Download Trades instead of OHLCV data ",-1)])),_:1,__:[18]},8,["modelValue"])]),n("div",an,[o($,{modelValue:r(g).customExchange,"onUpdate:modelValue":e[8]||(e[8]=a=>r(g).customExchange=a),class:"mb-2"},{default:p(()=>e[19]||(e[19]=[f(" Custom Exchange ",-1)])),_:1,__:[19]},8,["modelValue"]),o(z,{name:"fade"},{default:p(()=>[M(o(X,{modelValue:r(g).selectedExchange,"onUpdate:modelValue":e[9]||(e[9]=a=>r(g).selectedExchange=a)},null,8,["modelValue"]),[[N,r(g).customExchange]])]),_:1})])],512),[[N,r(h)]])]),_:1})]),n("div",rn,[o(B,{severity:"primary",onClick:V},{default:p(()=>e[20]||(e[20]=[f("Start Download",-1)])),_:1,__:[20]})])])])]),_:1})])}}}),ln={};function dn(t,l){const d=on;return s(),v(d,{class:"pt-4"})}const vn=me(ln,[["render",dn]]);export{vn as default};
//# sourceMappingURL=DownloadDataView-DcNCmkfT.js.map

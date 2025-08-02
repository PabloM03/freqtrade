import{Z as y,aa as _,c as s,a as p,a1 as $,N as g,H as E,e as h,d as P,r as w,o as H,U as M,w as F,l as b,f as m,s as R,i as U,n as W,k as f,F as V,b as r,g as j,h as c,a8 as O,B as T,_ as Z}from"./index-B2VjJQTc.js";import{_ as q}from"./check-CI6y9Q_q.js";import{_ as J}from"./plus-box-outline-CJYGTdMk.js";var K=`
    .p-inputgroup,
    .p-inputgroup .p-iconfield,
    .p-inputgroup .p-floatlabel,
    .p-inputgroup .p-iftalabel {
        display: flex;
        align-items: stretch;
        width: 100%;
    }

    .p-inputgroup .p-inputtext,
    .p-inputgroup .p-inputwrapper {
        flex: 1 1 auto;
        width: 1%;
    }

    .p-inputgroupaddon {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: dt('inputgroup.addon.padding');
        background: dt('inputgroup.addon.background');
        color: dt('inputgroup.addon.color');
        border-block-start: 1px solid dt('inputgroup.addon.border.color');
        border-block-end: 1px solid dt('inputgroup.addon.border.color');
        min-width: dt('inputgroup.addon.min.width');
    }

    .p-inputgroupaddon:first-child,
    .p-inputgroupaddon + .p-inputgroupaddon {
        border-inline-start: 1px solid dt('inputgroup.addon.border.color');
    }

    .p-inputgroupaddon:last-child {
        border-inline-end: 1px solid dt('inputgroup.addon.border.color');
    }

    .p-inputgroupaddon:has(.p-button) {
        padding: 0;
        overflow: hidden;
    }

    .p-inputgroupaddon .p-button {
        border-radius: 0;
    }

    .p-inputgroup > .p-component,
    .p-inputgroup > .p-inputwrapper > .p-component,
    .p-inputgroup > .p-iconfield > .p-component,
    .p-inputgroup > .p-floatlabel > .p-component,
    .p-inputgroup > .p-floatlabel > .p-inputwrapper > .p-component,
    .p-inputgroup > .p-iftalabel > .p-component,
    .p-inputgroup > .p-iftalabel > .p-inputwrapper > .p-component {
        border-radius: 0;
        margin: 0;
    }

    .p-inputgroupaddon:first-child,
    .p-inputgroup > .p-component:first-child,
    .p-inputgroup > .p-inputwrapper:first-child > .p-component,
    .p-inputgroup > .p-iconfield:first-child > .p-component,
    .p-inputgroup > .p-floatlabel:first-child > .p-component,
    .p-inputgroup > .p-floatlabel:first-child > .p-inputwrapper > .p-component,
    .p-inputgroup > .p-iftalabel:first-child > .p-component,
    .p-inputgroup > .p-iftalabel:first-child > .p-inputwrapper > .p-component {
        border-start-start-radius: dt('inputgroup.addon.border.radius');
        border-end-start-radius: dt('inputgroup.addon.border.radius');
    }

    .p-inputgroupaddon:last-child,
    .p-inputgroup > .p-component:last-child,
    .p-inputgroup > .p-inputwrapper:last-child > .p-component,
    .p-inputgroup > .p-iconfield:last-child > .p-component,
    .p-inputgroup > .p-floatlabel:last-child > .p-component,
    .p-inputgroup > .p-floatlabel:last-child > .p-inputwrapper > .p-component,
    .p-inputgroup > .p-iftalabel:last-child > .p-component,
    .p-inputgroup > .p-iftalabel:last-child > .p-inputwrapper > .p-component {
        border-start-end-radius: dt('inputgroup.addon.border.radius');
        border-end-end-radius: dt('inputgroup.addon.border.radius');
    }

    .p-inputgroup .p-component:focus,
    .p-inputgroup .p-component.p-focus,
    .p-inputgroup .p-inputwrapper-focus,
    .p-inputgroup .p-component:focus ~ label,
    .p-inputgroup .p-component.p-focus ~ label,
    .p-inputgroup .p-inputwrapper-focus ~ label {
        z-index: 1;
    }

    .p-inputgroup > .p-button:not(.p-button-icon-only) {
        width: auto;
    }

    .p-inputgroup .p-iconfield + .p-iconfield .p-inputtext {
        border-inline-start: 0;
    }
`,L={root:"p-inputgroup"},Q=y.extend({name:"inputgroup",style:K,classes:L}),X={name:"BaseInputGroup",extends:_,style:Q,provide:function(){return{$pcInputGroup:this,$parentInstance:this}}},Y={name:"InputGroup",extends:X,inheritAttrs:!1};function nn(n,a,i,l,e,t){return p(),s("div",g({class:n.cx("root")},n.ptmi("root")),[$(n.$slots,"default")],16)}Y.render=nn;var en={root:"p-inputgroupaddon"},tn=y.extend({name:"inputgroupaddon",classes:en}),on={name:"BaseInputGroupAddon",extends:_,style:tn,provide:function(){return{$pcInputGroupAddon:this,$parentInstance:this}}},pn={name:"InputGroupAddon",extends:on,inheritAttrs:!1};function rn(n,a,i,l,e,t){return p(),s("div",g({class:n.cx("root")},n.ptmi("root")),[$(n.$slots,"default")],16)}pn.render=rn;const sn={viewBox:"0 0 24 24",width:"1.2em",height:"1.2em"};function an(n,a){return p(),s("svg",sn,a[0]||(a[0]=[h("path",{fill:"currentColor",d:"M19 21H8V7h11m0-2H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2m-3-4H4a2 2 0 0 0-2 2v14h2V3h12z"},null,-1)]))}const ln=E({name:"mdi-content-copy",render:an}),un={class:"grow"},$n=P({__name:"EditValue",props:{modelValue:{},allowEdit:{type:Boolean,default:!1},allowAdd:{type:Boolean,default:!1},allowDuplicate:{type:Boolean,default:!1},editableName:{},alignVertical:{type:Boolean,default:!1}},emits:["delete","new","duplicate","rename"],setup(n,{emit:a}){const i=n,l=a,e=w(""),t=w(0);H(()=>{e.value=i.modelValue});function x(){t.value=0,e.value=i.modelValue}function B(){e.value=e.value+" (copy)",t.value=3}function S(){e.value="",t.value=2}M(()=>i.modelValue,()=>{e.value=i.modelValue});function k(){t.value===2?l("new",e.value):t.value===3?l("duplicate",i.modelValue,e.value):l("rename",i.modelValue,e.value),t.value=0}return(o,u)=>{const N=R,A=O,d=j,C=ln,I=T,z=J,G=q,D=Z;return p(),s("form",{class:"flex flex-row",onSubmit:F(k,["prevent"])},[h("div",un,[m(t)===0?$(o.$slots,"default",{key:0}):(p(),b(N,{key:1,modelValue:m(e),"onUpdate:modelValue":u[0]||(u[0]=v=>U(e)?e.value=v:null),size:"small",fluid:""},null,8,["modelValue"]))]),h("div",{class:W(["mt-auto flex gap-1 ms-1",o.alignVertical?"flex-col":"flex-row"])},[o.allowEdit&&m(t)===0?(p(),s(V,{key:0},[r(d,{size:"small",severity:"secondary",title:`Edit this ${o.editableName}.`,onClick:u[1]||(u[1]=v=>t.value=1)},{icon:c(()=>[r(A)]),_:1},8,["title"]),o.allowDuplicate?(p(),b(d,{key:0,size:"small",severity:"secondary",title:`Duplicate ${o.editableName}.`,onClick:B},{icon:c(()=>[r(C)]),_:1},8,["title"])):f("",!0),r(d,{size:"small",severity:"secondary",title:`Delete this ${o.editableName}.`,onClick:u[2]||(u[2]=v=>o.$emit("delete",o.modelValue))},{icon:c(()=>[r(I)]),_:1},8,["title"])],64)):f("",!0),o.allowAdd&&m(t)===0?(p(),b(d,{key:1,size:"small",title:`Add new ${o.editableName}.`,severity:"primary",onClick:S},{icon:c(()=>[r(z)]),_:1},8,["title"])):f("",!0),m(t)!==0?(p(),s(V,{key:2},[r(d,{size:"small",title:`Add new ${o.editableName}`,severity:"primary",onClick:k},{icon:c(()=>[r(G)]),_:1},8,["title"]),r(d,{size:"small",title:"Abort",severity:"secondary",onClick:x},{icon:c(()=>[r(D)]),_:1})],64)):f("",!0)],2)],32)}}});var dn=`
    .p-progressspinner {
        position: relative;
        margin: 0 auto;
        width: 100px;
        height: 100px;
        display: inline-block;
    }

    .p-progressspinner::before {
        content: '';
        display: block;
        padding-top: 100%;
    }

    .p-progressspinner-spin {
        height: 100%;
        transform-origin: center center;
        width: 100%;
        position: absolute;
        top: 0;
        bottom: 0;
        left: 0;
        right: 0;
        margin: auto;
        animation: p-progressspinner-rotate 2s linear infinite;
    }

    .p-progressspinner-circle {
        stroke-dasharray: 89, 200;
        stroke-dashoffset: 0;
        stroke: dt('progressspinner.colorOne');
        animation:
            p-progressspinner-dash 1.5s ease-in-out infinite,
            p-progressspinner-color 6s ease-in-out infinite;
        stroke-linecap: round;
    }

    @keyframes p-progressspinner-rotate {
        100% {
            transform: rotate(360deg);
        }
    }
    @keyframes p-progressspinner-dash {
        0% {
            stroke-dasharray: 1, 200;
            stroke-dashoffset: 0;
        }
        50% {
            stroke-dasharray: 89, 200;
            stroke-dashoffset: -35px;
        }
        100% {
            stroke-dasharray: 89, 200;
            stroke-dashoffset: -124px;
        }
    }
    @keyframes p-progressspinner-color {
        100%,
        0% {
            stroke: dt('progressspinner.color.one');
        }
        40% {
            stroke: dt('progressspinner.color.two');
        }
        66% {
            stroke: dt('progressspinner.color.three');
        }
        80%,
        90% {
            stroke: dt('progressspinner.color.four');
        }
    }
`,cn={root:"p-progressspinner",spin:"p-progressspinner-spin",circle:"p-progressspinner-circle"},mn=y.extend({name:"progressspinner",style:dn,classes:cn}),gn={name:"BaseProgressSpinner",extends:_,props:{strokeWidth:{type:String,default:"2"},fill:{type:String,default:"none"},animationDuration:{type:String,default:"2s"}},style:mn,provide:function(){return{$pcProgressSpinner:this,$parentInstance:this}}},fn={name:"ProgressSpinner",extends:gn,inheritAttrs:!1,computed:{svgStyle:function(){return{"animation-duration":this.animationDuration}}}},hn=["fill","stroke-width"];function vn(n,a,i,l,e,t){return p(),s("div",g({class:n.cx("root"),role:"progressbar"},n.ptmi("root")),[(p(),s("svg",g({class:n.cx("spin"),viewBox:"25 25 50 50",style:t.svgStyle},n.ptm("spin")),[h("circle",g({class:n.cx("circle"),cx:"50",cy:"50",r:"20",fill:n.fill,"stroke-width":n.strokeWidth,strokeMiterlimit:"10"},n.ptm("circle")),null,16,hn)],16))],16)}fn.render=vn;export{$n as _,pn as a,fn as b,ln as c,Y as s};
//# sourceMappingURL=index-B2YlbmLi.js.map

import gsap from "gsap";
import {CustomEase} from "gsap/CustomEase";
import {Flip} from "gsap/Flip";
import {ScrollTrigger} from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger, Flip, CustomEase);

CustomEase.create("dduSlam", "M0,0 C0.1,0.7 0.2,1 1,1");
CustomEase.create("dduReveal", "M0,0 C0.16,1 0.3,1 1,1");
CustomEase.create("dduSnap", "M0,0 C0.2,0.8 0.2,1 1,1");

export {gsap, Flip, ScrollTrigger};

export const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Split element text into word spans for staggered reveals. */
export function splitWords(el: HTMLElement): HTMLElement[] {
  if (el.dataset.split === "words") {
    return Array.from(el.querySelectorAll<HTMLElement>("[data-word]"));
  }
  const text = el.textContent ?? "";
  el.textContent = "";
  el.dataset.split = "words";
  const words = text.split(/(\s+)/);
  const nodes: HTMLElement[] = [];
  for (const part of words) {
    if (!part) continue;
    if (/^\s+$/.test(part)) {
      el.appendChild(document.createTextNode(part));
      continue;
    }
    const wrap = document.createElement("span");
    wrap.className = "gsap-word-wrap";
    wrap.style.display = "inline-block";
    wrap.style.overflow = "hidden";
    wrap.style.verticalAlign = "top";
    const word = document.createElement("span");
    word.dataset.word = "";
    word.className = "gsap-word";
    word.style.display = "inline-block";
    word.textContent = part;
    wrap.appendChild(word);
    el.appendChild(wrap);
    nodes.push(word);
  }
  return nodes;
}

export function killContext(scope: gsap.Context | null | undefined) {
  scope?.revert();
}

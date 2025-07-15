"use client";
import { motion } from "framer-motion";
import clsx from "clsx";
type Props = { leftPct:number; centerPct:number; rightPct:number; compact?:boolean };
export default function BiasGauge({ leftPct, centerPct, rightPct, compact }: Props) {
  const bar = (w:number, color:string) => (
    <motion.div
      className={clsx("h-2", color)}
      style={{ width:`${w}%` }}
      transition={{ type:"spring", stiffness:80 }}
    />
  );
  return (
    <div className={clsx("flex w-full rounded-full overflow-hidden", compact && "h-1")}> 
      {bar(leftPct,"bg-bias-left")}
      {bar(centerPct,"bg-bias-center")}
      {bar(rightPct,"bg-bias-right")}
    </div>
  );
}

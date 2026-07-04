import { ScreenPlaceholder } from "@/components/screen-placeholder";

export default function BridgePage() {
  return (
    <ScreenPlaceholder
      module="Trace"
      title="Bridge View"
      phase="Phase 2"
      blurb="QRIS → mule → exchange → USDT Sankey (d3-sankey), suspected on-ramp feed ranked by confidence, and mule-network stats across the fiat│bridge│crypto split."
    />
  );
}

import * as React from "react";
import { cn } from "../../lib/utils";

type ScrollAreaProps = React.HTMLAttributes<HTMLDivElement> & {
  viewportClassName?: string;
  viewportRef?: React.Ref<HTMLDivElement>;
  viewportOnScroll?: React.UIEventHandler<HTMLDivElement>;
};

function ScrollArea({
  className,
  viewportClassName,
  viewportRef,
  viewportOnScroll,
  children,
  ...props
}: ScrollAreaProps) {
  return (
    <div
      className={cn("relative overflow-hidden", className)}
      {...props}
    >
      <div
        ref={viewportRef}
        onScroll={viewportOnScroll}
        className={cn("h-full w-full overflow-auto no-scrollbar overscroll-contain", viewportClassName)}
      >
        {children}
      </div>
    </div>
  );
}

export { ScrollArea };

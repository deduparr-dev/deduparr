import * as React from "react";
import * as ToastPrimitives from "@radix-ui/react-toast";
import { cva, type VariantProps } from "class-variance-authority";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

const ToastProvider = ToastPrimitives.Provider;

interface ToastViewportProps
  extends React.ComponentPropsWithoutRef<typeof ToastPrimitives.Viewport> {
  ref?: React.Ref<React.ElementRef<typeof ToastPrimitives.Viewport>>;
}

const ToastViewport = ({ className, ref, ...props }: ToastViewportProps) => (
  <ToastPrimitives.Viewport
    ref={ref}
    className={cn(
      "fixed top-0 z-[100] flex max-h-screen w-full flex-col-reverse p-4 sm:bottom-0 sm:right-0 sm:top-auto sm:flex-col md:max-w-[420px]",
      className
    )}
    {...props}
  />
);
ToastViewport.displayName = ToastPrimitives.Viewport.displayName;

const toastVariants = cva(
  "group pointer-events-auto relative flex w-full items-center justify-between space-x-4 overflow-hidden rounded-md border p-6 pr-8 shadow-lg transition-all data-[swipe=cancel]:translate-x-0 data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)] data-[swipe=move]:transition-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[swipe=end]:animate-out data-[state=closed]:fade-out-80 data-[state=closed]:slide-out-to-right-full data-[state=open]:slide-in-from-top-full data-[state=open]:sm:slide-in-from-bottom-full",
  {
    variants: {
      variant: {
        default: "border bg-background text-foreground",
        destructive:
          "destructive group border-destructive bg-destructive text-destructive-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

interface ToastProps
  extends React.ComponentPropsWithoutRef<typeof ToastPrimitives.Root>,
    VariantProps<typeof toastVariants> {
  ref?: React.Ref<React.ElementRef<typeof ToastPrimitives.Root>>;
}

const Toast = ({ className, variant, ref, ...props }: ToastProps) => {
  return (
    <ToastPrimitives.Root
      ref={ref}
      className={cn(toastVariants({ variant }), className)}
      {...props}
    />
  );
};
Toast.displayName = ToastPrimitives.Root.displayName;

interface ToastActionProps extends React.ComponentPropsWithoutRef<typeof ToastPrimitives.Action> {
  ref?: React.Ref<React.ElementRef<typeof ToastPrimitives.Action>>;
}

const ToastAction = ({ className, ref, ...props }: ToastActionProps) => (
  <ToastPrimitives.Action
    ref={ref}
    className={cn(
      "inline-flex h-8 shrink-0 items-center justify-center rounded-md border bg-transparent px-3 text-sm font-medium ring-offset-background transition-colors group-[.destructive]:border-muted/40 hover:bg-secondary group-[.destructive]:hover:border-destructive/30 group-[.destructive]:hover:bg-destructive group-[.destructive]:hover:text-destructive-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 group-[.destructive]:focus:ring-destructive disabled:pointer-events-none disabled:opacity-50",
      className
    )}
    {...props}
  />
);
ToastAction.displayName = ToastPrimitives.Action.displayName;

interface ToastCloseProps extends React.ComponentPropsWithoutRef<typeof ToastPrimitives.Close> {
  ref?: React.Ref<React.ElementRef<typeof ToastPrimitives.Close>>;
}

const ToastClose = ({ className, ref, ...props }: ToastCloseProps) => (
  <ToastPrimitives.Close
    ref={ref}
    className={cn(
      "absolute right-2 top-2 rounded-md p-1 text-foreground/50 opacity-0 transition-opacity group-hover:opacity-100 group-[.destructive]:text-red-300 hover:text-foreground group-[.destructive]:hover:text-red-50 focus:opacity-100 focus:outline-none focus:ring-2 group-[.destructive]:focus:ring-red-400 group-[.destructive]:focus:ring-offset-red-600",
      className
    )}
    toast-close=""
    {...props}
  >
    <X className="h-4 w-4" />
  </ToastPrimitives.Close>
);
ToastClose.displayName = ToastPrimitives.Close.displayName;

interface ToastTitleProps extends React.ComponentPropsWithoutRef<typeof ToastPrimitives.Title> {
  ref?: React.Ref<React.ElementRef<typeof ToastPrimitives.Title>>;
}

const ToastTitle = ({ className, ref, ...props }: ToastTitleProps) => (
  <ToastPrimitives.Title ref={ref} className={cn("text-sm font-semibold", className)} {...props} />
);
ToastTitle.displayName = ToastPrimitives.Title.displayName;

interface ToastDescriptionProps
  extends React.ComponentPropsWithoutRef<typeof ToastPrimitives.Description> {
  ref?: React.Ref<React.ElementRef<typeof ToastPrimitives.Description>>;
}

const ToastDescription = ({ className, ref, ...props }: ToastDescriptionProps) => (
  <ToastPrimitives.Description
    ref={ref}
    className={cn("text-sm opacity-90", className)}
    {...props}
  />
);
ToastDescription.displayName = ToastPrimitives.Description.displayName;

type ToastActionElement = React.ReactElement<typeof ToastAction>;

export {
  type ToastProps,
  type ToastActionElement,
  ToastProvider,
  ToastViewport,
  Toast,
  ToastTitle,
  ToastDescription,
  ToastClose,
  ToastAction,
};

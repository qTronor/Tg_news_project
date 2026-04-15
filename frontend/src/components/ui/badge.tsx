import { cn } from "@/lib/utils";

type Variant = "default" | "topic" | "entity" | "sentiment" | "new" | "outline";

interface BadgeProps {
  children: React.ReactNode;
  variant?: Variant;
  color?: string;
  className?: string;
  onClick?: () => void;
}

const variantStyles: Record<Variant, string> = {
  default: "bg-muted text-muted-foreground",
  topic: "bg-primary/10 text-primary",
  entity: "border border-current/20",
  sentiment: "",
  new: "bg-destructive/10 text-destructive font-semibold animate-pulse",
  outline: "border border-border text-muted-foreground",
};

export function Badge({ children, variant = "default", color, className, onClick }: BadgeProps) {
  return (
    <span
      onClick={onClick}
      style={color ? { color, backgroundColor: `${color}15`, borderColor: `${color}30` } : undefined}
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium transition-all duration-200",
        variantStyles[variant],
        onClick && "cursor-pointer hover:opacity-80",
        className
      )}
    >
      {children}
    </span>
  );
}

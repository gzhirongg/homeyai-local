import Link from "next/link";

/** Matches `public/logo.svg` viewBox (400×144). */
const LOGO_ASPECT = 400 / 144;

const sizeConfig = {
    sm: { height: 32, className: "h-8" },
    md: { height: 40, className: "h-10" },
    lg: { height: 48, className: "h-12" },
} as const;

type LogoSize = keyof typeof sizeConfig;

type LogoProps = {
    size?: LogoSize;
    className?: string;
    linkClassName?: string;
    href?: string | null;
    priority?: boolean;
};

export default function Logo({
    size = "sm",
    className = "",
    linkClassName = "",
    href = "/",
    priority = false,
}: LogoProps) {
    const { height, className: heightClass } = sizeConfig[size];
    const width = Math.round(height * LOGO_ASPECT);

    const image = (
        // eslint-disable-next-line @next/next/no-img-element
        <img
            src="/logo.svg"
            alt="HomeyAI"
            width={width}
            height={height}
            className={`w-auto object-contain ${heightClass} ${className}`.trim()}
            fetchPriority={priority ? "high" : undefined}
        />
    );

    if (href) {
        return (
            <Link href={href} className={`inline-flex shrink-0 items-center ${linkClassName}`.trim()}>
                {image}
            </Link>
        );
    }

    return image;
}

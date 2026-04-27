import Image from "next/image";

type BrandLogoProps = {
  className?: string;
  size?: number;
};

export function BrandLogo({
  className = "",
  size = 48,
}: BrandLogoProps) {
  return (
    <Image
      src="/brand/job-copilot-logo.png"
      alt="Job Application Copilot logo"
      width={size}
      height={size}
      className={className}
      priority
    />
  );
}

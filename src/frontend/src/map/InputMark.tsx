export interface InputMarkProps {
  locked: boolean;
}

export function InputMark({ locked }: InputMarkProps) {
  const word = locked ? "задано" : "нужно задать";
  const tone = locked ? "locked" : "await";
  return (
    <span className={`mapnode__word mapnode__word--icon mapnode__word--input-${tone}`} title={word}>
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        {locked ? (
          <path d="M2.6 8.4 L6.4 12.4 L13.4 4.2" />
        ) : (
          <>
            <path d="M8 1.9 L14.6 13.3 H1.4 Z" />
            <path d="M8 6.3 V9.3" />
            <path d="M8 11.5 V11.6" />
          </>
        )}
      </svg>
    </span>
  );
}

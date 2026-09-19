import { useCallback, useEffect, useId, useRef, useState } from "react";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  label: string;
  value: string;
  options: SelectOption[];
  disabled?: boolean;
  onChange: (value: string) => void;
}

function indexOf(options: SelectOption[], value: string): number {
  const found = options.findIndex((item) => item.value === value);
  return found < 0 ? 0 : found;
}

export function Select({ label, value, options, disabled, onChange }: SelectProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(() => indexOf(options, value));
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const listId = useId();
  const labelId = useId();
  const current = options.find((item) => item.value === value) ?? null;

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }, []);

  const commit = useCallback(
    (index: number) => {
      const picked = options[index];
      if (picked) onChange(picked.value);
      close(true);
    },
    [options, onChange, close]
  );

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    const onFocus = (event: FocusEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer, true);
    document.addEventListener("focusin", onFocus);
    return () => {
      document.removeEventListener("pointerdown", onPointer, true);
      document.removeEventListener("focusin", onFocus);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const node = list.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  useEffect(() => {
    if (disabled && open) setOpen(false);
  }, [disabled, open]);

  const openAt = useCallback(
    (index: number) => {
      setActive(index);
      setOpen(true);
    },
    []
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    const last = options.length - 1;
    if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        event.stopPropagation();
        close(true);
      }
      return;
    }
    if (event.key === "Tab") {
      if (open) setOpen(false);
      return;
    }
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openAt(indexOf(options, value));
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index >= last ? last : index + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index <= 0 ? 0 : index - 1));
    } else if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActive(last);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      commit(active);
    }
  };

  return (
    <div className="ctl" ref={wrap}>
      <span className="ctl__label" id={labelId}>
        {label}
      </span>
      <div className="ctl__wrap">
        <button
          type="button"
          ref={trigger}
          className="ctl__control ctl__control--select"
          disabled={disabled}
          role="combobox"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-labelledby={`${labelId} ${listId}-value`}
          aria-activedescendant={open ? `${listId}-${active}` : undefined}
          onKeyDown={onKeyDown}
          onClick={() => (open ? setOpen(false) : openAt(indexOf(options, value)))}
        >
          <span className="ctl__value" id={`${listId}-value`}>
            {current ? current.label : "—"}
          </span>
          <span className="ctl__caret" aria-hidden="true" />
        </button>
        {open ? (
          <ul
            className="ctl__list"
            ref={list}
            id={listId}
            role="listbox"
            aria-labelledby={labelId}
          >
            {options.map((item, index) => (
              <li
                key={item.value}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={item.value === value}
                data-active={index === active}
                className="ctl__option"
                onPointerMove={() => setActive(index)}
                onClick={() => commit(index)}
              >
                {item.label}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

export interface SegmentedOption<T extends string = string> {
  value: T;
  label: string;
}

export interface SegmentedControlProps<T extends string = string> {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
}

/** Horizontal set of mutually-exclusive buttons (e.g. Weekly / Daily / Hourly). */
export function SegmentedControl<T extends string = string>({
  options,
  value,
  onChange,
}: SegmentedControlProps<T>) {
  return (
    <div className="ju-segmented">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={option.value === value ? "ju-active" : undefined}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

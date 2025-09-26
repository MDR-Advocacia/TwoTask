"use client"

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Check, X, ChevronsUpDown } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
} from "@/components/ui/command"
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/popover"
import { Separator } from "./separator"

const multiSelectVariants = cva(
    "m-1",
    {
        variants: {
            variant: {
                default:
                    "border-foreground/10 text-foreground",
                secondary:
                    "border-foreground/10 bg-secondary text-secondary-foreground",
                destructive:
                    "border-transparent bg-destructive text-destructive-foreground",
                inverted: "inverted",
            },
        },
        defaultVariants: {
            variant: "default",
        },
    }
)

interface MultiSelectProps
    extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof multiSelectVariants> {
    options: {
        label: string
        value: string
        icon?: React.ComponentType<{ className?: string }>
    }[]
    onValueChange: (value: string[]) => void
    defaultValue: string[]
    placeholder?: string
    animation?: number
    maxCount?: number
    asChild?: boolean
    className?: string
}

const MultiSelect = React.forwardRef<
    HTMLButtonElement,
    MultiSelectProps
>(
    (
        {
            options,
            onValueChange,
            variant,
            defaultValue = [],
            placeholder = "Select options",
            animation = 0,
            maxCount = 3,
            asChild = false,
            className,
            ...props
        },
        ref
    ) => {
        const [selectedValues, setSelectedValues] = React.useState(defaultValue)
        const [isPopoverOpen, setIsPopoverOpen] = React.useState(false)
        const [isAnimating, setIsAnimating] = React.useState(false)

        React.useEffect(() => {
            if (JSON.stringify(selectedValues) !== JSON.stringify(defaultValue)) {
                setSelectedValues(defaultValue)
            }
        }, [defaultValue, selectedValues])

        const handleInputKeyDown = (
            event: React.KeyboardEvent<HTMLInputElement>
        ) => {
            if (event.key === "Enter") {
                setIsPopoverOpen(true)
            } else if (event.key === "Backspace" && !event.currentTarget.value) {
                const newSelectedValues = [...selectedValues]
                newSelectedValues.pop()
                setSelectedValues(newSelectedValues)
                onValueChange(newSelectedValues)
            }
        }

        const toggleOption = (value: string) => {
            const newSelectedValues = selectedValues.includes(value)
                ? selectedValues.filter((v) => v !== value)
                : [...selectedValues, value]
            setSelectedValues(newSelectedValues)
            onValueChange(newSelectedValues)
        }

        const handleClear = () => {
            setSelectedValues([])
            onValueChange([])
        }

        const handleTogglePopover = () => {
            setIsPopoverOpen((prev) => !prev)
        }

        const DURATION = animation > 0 ? animation : 50
        const startAnimation = () => {
            setIsAnimating(true)
            setTimeout(() => {
                setIsAnimating(false)
            }, DURATION * maxCount)
        }

        const getBadgeStyle = (index: number) => {
            if (isAnimating) {
                return {
                    animationDelay: `${index * DURATION}ms`,
                    animationDuration: `${DURATION}ms`,
                }
            }
            return {}
        }

        return (
            <Popover open={isPopoverOpen} onOpenChange={setIsPopoverOpen}>
                <PopoverTrigger asChild>
                    <Button
                        ref={ref}
                        {...props}
                        onClick={handleTogglePopover}
                        className={cn(
                            "flex w-full p-1 rounded-md border min-h-10 h-auto items-center justify-between bg-inherit hover:bg-card",
                            className
                        )}
                    >
                        {selectedValues.length > 0 ? (
                            <div className="flex justify-between items-center w-full">
                                <div className="flex flex-wrap items-center">
                                    {selectedValues.slice(0, maxCount).map((value, index) => {
                                        const option = options.find((o) => o.value === value)
                                        const Icon = option?.icon
                                        return (
                                            <Badge
                                                key={value}
                                                className={cn(
                                                    isAnimating && "animate-out fade-out-0",
                                                    multiSelectVariants({ variant })
                                                )}
                                                style={getBadgeStyle(index)}
                                            >
                                                {Icon && <Icon className="mr-2 h-4 w-4" />}
                                                {option?.label}
                                                <X
                                                    className="ml-2 h-4 w-4 cursor-pointer"
                                                    onClick={(event) => {
                                                        event.stopPropagation()
                                                        toggleOption(value)
                                                    }}
                                                />
                                            </Badge>
                                        )
                                    })}
                                    {selectedValues.length > maxCount && (
                                        <Badge
                                            className={cn(
                                                "bg-transparent text-foreground border-foreground/10",
                                                isAnimating && "animate-out fade-out-0"
                                            )}
                                            style={getBadgeStyle(maxCount)}
                                        >
                                            +{selectedValues.length - maxCount}
                                        </Badge>
                                    )}
                                </div>
                                <div className="flex items-center justify-between">
                                    <X
                                        className="h-4 w-4 cursor-pointer"
                                        onClick={(event) => {
                                            event.stopPropagation()
                                            handleClear()
                                            startAnimation()
                                        }}
                                    />
                                    <Separator
                                        orientation="vertical"
                                        className="h-full min-h-6"
                                    />
                                    <ChevronsUpDown className="h-4 w-4"
                                    />
                                </div>
                            </div>
                        ) : (
                            <div className="flex items-center justify-between w-full mx-auto">
                                <span className="text-sm text-muted-foreground mx-3">
                                    {placeholder}
                                </span>
                                <ChevronsUpDown className="h-4 w-4 mx-2" />
                            </div>
                        )}
                    </Button>
                </PopoverTrigger>
                <PopoverContent
                    className="w-[200px] p-0"
                    align="start"
                    onEscapeKeyDown={() => setIsPopoverOpen(false)}
                >
                    <Command>
                        <CommandInput
                            placeholder="Search..."
                            onKeyDown={handleInputKeyDown}
                        />
                        <CommandList>
                            <CommandEmpty>No results found.</CommandEmpty>
                            <CommandGroup>
                                {options.map((option) => {
                                    const isSelected = selectedValues.includes(option.value)
                                    return (
                                        <CommandItem
                                            key={option.value}
                                            onSelect={() => toggleOption(option.value)}
                                            style={{
                                                pointerEvents: "auto",
                                                opacity: 1,
                                            }}
                                            className="cursor-pointer"
                                        >
                                            <div
                                                className={cn(
                                                    "mr-2 flex h-4 w-4 items-center justify-center rounded-sm border border-primary",
                                                    isSelected
                                                        ? "bg-primary text-primary-foreground"
                                                        : "opacity-50 [&_svg]:invisible"
                                                )}
                                            >
                                                <Check className={cn("h-4 w-4")} />
                                            </div>
                                            {option.icon && (
                                                <option.icon className="mr-2 h-4 w-4 text-muted-foreground" />
                                            )}
                                            <span>{option.label}</span>
                                        </CommandItem>
                                    )
                                })}
                            </CommandGroup>
                            {selectedValues.length > 0 && (
                                <>
                                    <CommandSeparator />
                                    <CommandGroup>
                                        <CommandItem
                                            onSelect={handleClear}
                                            style={{
                                                pointerEvents: "auto",
                                                opacity: 1,
                                            }}
                                            className="cursor-pointer"
                                        >
                                            Clear
                                        </CommandItem>
                                    </CommandGroup>
                                </>
                            )}
                        </CommandList>
                    </Command>
                </PopoverContent>
            </Popover>
        )
    }
)

MultiSelect.displayName = "MultiSelect"

export { MultiSelect }
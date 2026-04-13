int HcclCheckLogLevel(int current_level, int target_level)
{
    return current_level <= target_level;
}

bool IsErrorToWarn()
{
    return false;
}